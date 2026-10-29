import hmac
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from ..deps import get_conn
from ..deps_auth import carregar_usuario
from ..email_service import enviar_codigo_login
from ..security_auth import (
    ACCESS_MIN, DUMMY_HASH, REFRESH_DIAS,
    criar_access_token, criar_token_2fa, decodificar, gerar_codigo_email,
    hash_codigo_email, hash_senha, hash_token, novo_refresh, precisa_rehash,
    verificar_senha,
)

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FALHAS = 5               # falhas dentro da janela => bloqueio temporário do usuário
JANELA_MIN = 15
CODIGO_VALIDADE_MIN = 10
CODIGO_MAX_TENTATIVAS = 5    # erros permitidos por código
REENVIO_SEG = 60             # intervalo mínimo entre e-mails
MAX_ENVIOS_HORA = 5


# ---------- schemas ----------
class LoginIn(BaseModel):
    email: str
    senha: str


class Verify2FAIn(BaseModel):
    token_temporario: str
    codigo: str


class TokenTempIn(BaseModel):
    token_temporario: str


class RefreshIn(BaseModel):
    refresh_token: str


# ---------- helpers ----------
def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


_ACOES_FALHA = ("falha", "bloqueado", "negado", "limite", "reutilizado", "expirado")


def _audit(conn, id_usuario, acao: str, request: Request, detalhes: dict | None = None):
    # log_acesso não tem coluna de detalhes: o nome da ação já carrega o essencial
    resultado = "falha" if any(p in acao for p in _ACOES_FALHA) else "sucesso"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO log_acesso (fk_usuario_id_usuario, acao, resultado, ip, data_hora) VALUES (%s, %s, %s, %s, now())",
            (id_usuario, acao, resultado, _ip(request)),
        )


def _negar(conn, request, id_usuario, acao, detalhes=None, msg="Credenciais inválidas", code=401):
    """Audita, COMMITA (senão o rollback da exceção apagaria o log) e levanta o erro."""
    _audit(conn, id_usuario, acao, request, detalhes)
    conn.commit()
    raise HTTPException(code, msg, headers={"WWW-Authenticate": "Bearer"} if code == 401 else None)


def _bloqueado(conn, id_usuario: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM log_acesso
             WHERE fk_usuario_id_usuario = %s
               AND acao IN ('login_falha', '2fa_falha')
               AND data_hora > now() - make_interval(mins => %s)
            """,
            (id_usuario, JANELA_MIN),
        )
        return cur.fetchone()[0] >= MAX_FALHAS


def _mascarar(email: str) -> str:
    nome, _, dominio = email.partition("@")
    return f"{nome[:1]}***@{dominio}"


def _emitir_sessao(conn, user: dict, request: Request, familia: uuid.UUID | None = None) -> dict:
    raw, h = novo_refresh()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO refresh_token (fk_usuario_id_usuario, familia, token_hash, expira_em, ip, user_agent)
            VALUES (%s, %s, %s, now() + make_interval(days => %s), %s, %s)
            """,
            (user["id_usuario"], str(familia or uuid.uuid4()), h, REFRESH_DIAS,
             _ip(request), request.headers.get("user-agent", "")[:255]),
        )
    return {
        "access_token": criar_access_token(user["id_usuario"], user["perfil"]),
        "refresh_token": raw,
        "token_type": "bearer",
        "expires_in": ACCESS_MIN * 60,
    }


def _usuario_do_token_temporario(conn, token: str) -> dict:
    payload = decodificar(token, "2fa")
    user = carregar_usuario(conn, int(payload["sub"]))
    if not user or not user["ativo"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido ou expirado")
    return user


def _gerar_e_enviar_codigo(conn, user: dict, background: BackgroundTasks) -> str:
    """Retorna 'enviado', 'cooldown' (já mandou há pouco) ou 'limite' (muitos envios na hora)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE criado_em > now() - interval '1 hour'),
                   coalesce(bool_or(criado_em > now() - make_interval(secs => %s)), false)
              FROM codigo_2fa_email WHERE fk_usuario_id_usuario = %s
            """,
            (REENVIO_SEG, user["id_usuario"]),
        )
        na_hora, em_cooldown = cur.fetchone()
        if na_hora >= MAX_ENVIOS_HORA:
            return "limite"
        if em_cooldown:
            return "cooldown"

        codigo = gerar_codigo_email()
        cur.execute("DELETE FROM codigo_2fa_email WHERE fk_usuario_id_usuario = %s AND criado_em < now() - interval '1 day'",
                    (user["id_usuario"],))
        # só o código mais novo vale
        cur.execute("UPDATE codigo_2fa_email SET usado_em = now() WHERE fk_usuario_id_usuario = %s AND usado_em IS NULL",
                    (user["id_usuario"],))
        cur.execute(
            """
            INSERT INTO codigo_2fa_email (fk_usuario_id_usuario, codigo_hash, expira_em)
            VALUES (%s, %s, now() + make_interval(mins => %s))
            """,
            (user["id_usuario"], hash_codigo_email(user["id_usuario"], codigo), CODIGO_VALIDADE_MIN),
        )
    # o e-mail só sai depois que a resposta é enviada (a tarefa roda após o commit abaixo, feito pelo chamador)
    background.add_task(enviar_codigo_login, user["email"], user["nome"], codigo, CODIGO_VALIDADE_MIN)
    return "enviado"


# ---------- login ----------
@router.post("/login")
def login(body: LoginIn, request: Request, background: BackgroundTasks, conn=Depends(get_conn)):
    email = body.email.strip().lower()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id_usuario, senha AS senha_hash, (status = 'ativo') AS ativo FROM usuario WHERE lower(email) = %s", (email,))
        row = cur.fetchone()

    if row and _bloqueado(conn, row["id_usuario"]):
        _negar(conn, request, row["id_usuario"], "login_bloqueado", msg="Muitas tentativas. Tente mais tarde.", code=429)

    # sempre roda um verify (mesmo sem usuário) para o tempo de resposta não revelar se o e-mail existe
    senha_ok = verificar_senha(body.senha, row["senha_hash"] if row else DUMMY_HASH)
    if not (row and senha_ok and row["ativo"]):
        _negar(conn, request, row["id_usuario"] if row else None, "login_falha", {"email": email})

    if precisa_rehash(row["senha_hash"]):
        with conn.cursor() as cur:
            cur.execute("UPDATE usuario SET senha = %s WHERE id_usuario = %s",
                        (hash_senha(body.senha), row["id_usuario"]))

    user = carregar_usuario(conn, row["id_usuario"])

    if os.getenv("LOGIN_2FA_EMAIL", "true").lower() != "true":
        sessao = _emitir_sessao(conn, user, request)
        _audit(conn, user["id_usuario"], "login_ok", request)
        conn.commit()
        return sessao

    resultado = _gerar_e_enviar_codigo(conn, user, background)
    if resultado == "limite":
        _negar(conn, request, user["id_usuario"], "2fa_envio_limite", msg="Muitos códigos solicitados. Tente mais tarde.", code=429)

    _audit(conn, user["id_usuario"], "login_senha_ok_codigo_enviado" if resultado == "enviado" else "login_senha_ok_codigo_pendente", request)
    conn.commit()
    return {
        "requer_2fa": True,
        "metodo": "email",
        "email_mascarado": _mascarar(user["email"]),
        "expira_em_min": CODIGO_VALIDADE_MIN,
        "token_temporario": criar_token_2fa(user["id_usuario"]),
    }


@router.post("/2fa/reenviar")
def reenviar_codigo(body: TokenTempIn, request: Request, background: BackgroundTasks, conn=Depends(get_conn)):
    user = _usuario_do_token_temporario(conn, body.token_temporario)
    if _bloqueado(conn, user["id_usuario"]):
        _negar(conn, request, user["id_usuario"], "2fa_bloqueado", msg="Muitas tentativas. Tente mais tarde.", code=429)

    resultado = _gerar_e_enviar_codigo(conn, user, background)
    if resultado != "enviado":
        msg = "Aguarde um minuto para pedir outro código." if resultado == "cooldown" else "Muitos códigos solicitados. Tente mais tarde."
        _negar(conn, request, user["id_usuario"], "2fa_reenvio_negado", {"motivo": resultado}, msg=msg, code=429)

    _audit(conn, user["id_usuario"], "2fa_codigo_reenviado", request)
    conn.commit()
    return {"email_mascarado": _mascarar(user["email"]), "expira_em_min": CODIGO_VALIDADE_MIN}


@router.post("/2fa/verify")
def verificar_2fa(body: Verify2FAIn, request: Request, conn=Depends(get_conn)):
    user = _usuario_do_token_temporario(conn, body.token_temporario)
    if _bloqueado(conn, user["id_usuario"]):
        _negar(conn, request, user["id_usuario"], "2fa_bloqueado", msg="Muitas tentativas. Tente mais tarde.", code=429)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id_codigo, codigo_hash, tentativas, (expira_em < now()) AS expirado
              FROM codigo_2fa_email
             WHERE fk_usuario_id_usuario = %s AND usado_em IS NULL
             ORDER BY criado_em DESC LIMIT 1
             FOR UPDATE
            """,
            (user["id_usuario"],),
        )
        cod = cur.fetchone()

    if not cod or cod["expirado"]:
        _negar(conn, request, user["id_usuario"], "2fa_codigo_expirado", msg="Código expirado. Peça um novo.")

    codigo = body.codigo.strip()
    esperado = hash_codigo_email(user["id_usuario"], codigo) if (codigo.isdigit() and len(codigo) == 6) else ""
    if not (esperado and hmac.compare_digest(esperado, cod["codigo_hash"])):
        with conn.cursor() as cur:
            # estourou as tentativas deste código => invalida (precisa pedir outro)
            cur.execute(
                """
                UPDATE codigo_2fa_email
                   SET tentativas = tentativas + 1,
                       usado_em = CASE WHEN tentativas + 1 >= %s THEN now() ELSE usado_em END
                 WHERE id_codigo = %s
                """,
                (CODIGO_MAX_TENTATIVAS, cod["id_codigo"]),
            )
        _negar(conn, request, user["id_usuario"], "2fa_falha", msg="Código inválido")

    with conn.cursor() as cur:
        cur.execute("UPDATE codigo_2fa_email SET usado_em = now() WHERE id_codigo = %s", (cod["id_codigo"],))
    sessao = _emitir_sessao(conn, user, request)
    _audit(conn, user["id_usuario"], "login_ok_2fa", request, {"metodo": "email"})
    conn.commit()
    return sessao


# ---------- refresh / logout ----------
@router.post("/refresh")
def refresh(body: RefreshIn, request: Request, conn=Depends(get_conn)):
    h = hash_token(body.refresh_token)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id_refresh_token, fk_usuario_id_usuario, familia, usado_em, revogado_em,
                   (expira_em < now()) AS expirado
              FROM refresh_token WHERE token_hash = %s FOR UPDATE
            """,
            (h,),
        )
        rt = cur.fetchone()

    if not rt:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token inválido")

    if rt["usado_em"] or rt["revogado_em"]:
        # token já rotacionado sendo reapresentado: possível roubo => derruba a sessão inteira
        with conn.cursor() as cur:
            cur.execute("UPDATE refresh_token SET revogado_em = now() WHERE familia = %s AND revogado_em IS NULL",
                        (rt["familia"],))
        _negar(conn, request, rt["fk_usuario_id_usuario"], "refresh_reutilizado", msg="Sessão encerrada")

    if rt["expirado"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token expirado")

    user = carregar_usuario(conn, rt["fk_usuario_id_usuario"])
    if not user or not user["ativo"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário inativo")

    with conn.cursor() as cur:
        cur.execute("UPDATE refresh_token SET usado_em = now() WHERE id_refresh_token = %s", (rt["id_refresh_token"],))
    sessao = _emitir_sessao(conn, user, request, familia=rt["familia"])
    conn.commit()
    return sessao


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshIn, request: Request, conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE refresh_token SET revogado_em = now()
             WHERE familia = (SELECT familia FROM refresh_token WHERE token_hash = %s)
               AND revogado_em IS NULL
            RETURNING fk_usuario_id_usuario
            """,
            (hash_token(body.refresh_token),),
        )
        r = cur.fetchone()
    if r:
        _audit(conn, r[0], "logout", request)
    conn.commit()