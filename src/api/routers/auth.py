import hmac
import os
import re
import secrets
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from src import config
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field 

from .. import seguranca_log, totp_db
from ..deps import get_conn
from ..deps_auth import carregar_usuario, get_current_user_sem_bloqueio
from ..email_service import enviar_aviso_conta_ativada, enviar_aviso_senha_alterada, enviar_codigo_login, enviar_link_reset_senha
from ..security_auth import (
    ACCESS_MIN, DUMMY_HASH, PENDING_MIN, REFRESH_DIAS,
    criar_access_token, criar_token_2fa, decodificar, gerar_codigo_email,
    hash_codigo_email, hash_senha, hash_token, normalizar_codigo_ativacao, novo_refresh, precisa_rehash,
    validar_politica_senha, verificar_senha,
)

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FALHAS = 5               # falhas dentro da janela => bloqueio temporário do usuário
JANELA_MIN = 15
CODIGO_VALIDADE_MIN = 10
CODIGO_MAX_TENTATIVAS = 5    # erros permitidos por código
REENVIO_SEG = 60             # intervalo mínimo entre e-mails
MAX_ENVIOS_HORA = 5
ATIVACAO_MAX_TENTATIVAS = 5
ATIVACAO_MAX_HORA_IP = 20
ATIVACAO_ERRO = "Código inválido ou expirado."

# recuperação de senha
RESET_VALIDADE_MIN = 30
RESET_MAX_HORA_USUARIO = 3   # links por usuário por hora
RESET_MAX_HORA_IP = 20       # pedidos por IP por hora (generoso: atrás de proxy vários usuários dividem o IP)
RESET_RESPOSTA = {"mensagem": "Se o e-mail estiver cadastrado, enviaremos um link para redefinir a senha."}
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

# cookie do refresh token (httpOnly: o JavaScript do front nunca enxerga o valor)
COOKIE_REFRESH = "refresh_token"
COOKIE_PATH = "/auth"        # o navegador só envia o cookie para as rotas /auth/*
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
# "lax" serve quando front e API estão no mesmo site (ex.: app.x.com e api.x.com).
# Em domínios totalmente diferentes use COOKIE_SAMESITE=none (exige COOKIE_SECURE=true).
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").lower()


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
    refresh_token: str | None = None   # opcional: o normal é vir pelo cookie


class TrocarSenhaIn(BaseModel):
    senha_atual: str
    senha_nova: str = Field(min_length=1, max_length=128)


class EsqueciSenhaIn(BaseModel):
    email: str

class AtivarContaIn(BaseModel):
    email: str
    codigo: str
    senha_nova: str = Field(min_length=1, max_length=128)
    confirmar_senha: str
    aceite_termos: bool

class RedefinirSenhaIn(BaseModel):
    token: str
    senha_nova: str = Field(min_length=1, max_length=128)
    desconectar_outros: bool = True


import ipaddress

# ---------- helpers ----------
def _ip(request: Request) -> str | None:
    if not request.client or not request.client.host:
        return "127.0.0.1"
    try:
        ipaddress.ip_address(request.client.host)
        return request.client.host
    except ValueError:
        return "127.0.0.1"


_ACOES_FALHA = ("falha", "bloqueado", "negado", "limite", "reutilizado", "expirado")


def _audit(conn, id_usuario, acao: str, request: Request, detalhes: dict | None = None):
    # log_acesso não tem coluna de detalhes: o nome da ação já carrega o essencial
    resultado = "falha" if any(p in acao for p in _ACOES_FALHA) else "sucesso"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO log_acesso (fk_usuario_id_usuario, acao, resultado, ip, data_hora) VALUES (%s, %s, %s, %s, (now() AT TIME ZONE 'UTC'))",
            (id_usuario, acao, resultado, _ip(request)),
        )


def _negar(conn, request, id_usuario, acao, detalhes=None, msg="Credenciais inválidas", code=401):
    """Audita, COMMITA (senão o rollback da exceção apagaria o log) e levanta o erro."""
    _audit(conn, id_usuario, acao, request, detalhes)
    conn.commit()
    raise HTTPException(code, msg, headers={"WWW-Authenticate": "Bearer"} if code == 401 else None)


def _bloqueio_restante(conn, id_usuario: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT CEIL(EXTRACT(EPOCH FROM (data_hora + make_interval(mins => %(j)s) - (now() AT TIME ZONE 'UTC'))))
              FROM (
                SELECT data_hora FROM log_acesso
                 WHERE fk_usuario_id_usuario = %(u)s
                   AND acao IN ('login_falha', '2fa_falha', 'senha_atual_falha')
                   AND data_hora > (now() AT TIME ZONE 'UTC') - make_interval(mins => %(j)s)
                   AND data_hora > COALESCE(
                         (SELECT max(data_hora) FROM log_acesso
                           WHERE fk_usuario_id_usuario = %(u)s AND acao IN ('senha_redefinida', 'conta_ativada')),
                         '-infinity')
                 ORDER BY data_hora DESC
                OFFSET %(m)s LIMIT 1
              ) f
            """,
            {"j": JANELA_MIN, "u": id_usuario, "m": MAX_FALHAS - 1},
        )
        row = cur.fetchone()
    return max(int(row[0]), 0) if row else 0


def _bloqueado(conn, id_usuario: int) -> bool:
    return _bloqueio_restante(conn, id_usuario) > 0


def _negar_bloqueio(conn, request, id_usuario, acao):
    segundos = _bloqueio_restante(conn, id_usuario)
    _audit(conn, id_usuario, acao, request)
    conn.commit()
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        {"codigo": "CONTA_BLOQUEADA", "mensagem": "Conta temporariamente bloqueada.", "segundos_restantes": segundos},
        headers={"Retry-After": str(segundos)},
    )


def _exigir_politica(senha: str, email: str):
    faltando = validar_politica_senha(senha, email)
    if faltando:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"codigo": "SENHA_FRACA", "requisitos_faltando": faltando})


def _mascarar(email: str) -> str:
    nome, _, dominio = email.partition("@")
    return f"{nome[:1]}***@{dominio}"


def _set_cookie_refresh(response: Response, raw: str) -> None:
    response.set_cookie(
        COOKIE_REFRESH, raw,
        max_age=REFRESH_DIAS * 86400,
        httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE, path=COOKIE_PATH,
    )


def _limpar_cookie_refresh(response: Response) -> None:
    response.delete_cookie(
        COOKIE_REFRESH, path=COOKIE_PATH,
        httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
    )


_VERCEL_ORIGIN_RE = re.compile(r"^https://[a-zA-Z0-9-]+\.vercel\.app$")


def _checar_origem(request: Request) -> None:
    """Defesa extra contra CSRF nas rotas que usam o cookie (vale também com SameSite=None)."""
    origem = request.headers.get("origin")
    if origem and origem not in config.CORS_ORIGINS and not _VERCEL_ORIGIN_RE.match(origem):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origem não permitida")


def _emitir_sessao(conn, user: dict, request: Request, response: Response,
                   familia: uuid.UUID | None = None) -> dict:
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
    _set_cookie_refresh(response, raw)   # o refresh vai só no cookie, não no JSON
    return {
        "access_token": criar_access_token(user["id_usuario"], user["perfil"]),
        "token_type": "bearer",
        "expires_in": ACCESS_MIN * 60,
        "deve_trocar_senha": bool(user.get("deve_trocar_senha")),
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


class Preferencia2FAIn(BaseModel):
    email_ativo: bool


def _tem_2fa_email_ativo(conn, id_usuario: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ativo FROM notificacao_preferencia
             WHERE fk_usuario_id_usuario = %s AND canal = '2fa_email'
            """,
            (id_usuario,),
        )
        row = cur.fetchone()
    return bool(row and row[0])


@router.get("/2fa/preferencia")
def obter_preferencia_2fa(user=Depends(get_current_user_sem_bloqueio), conn=Depends(get_conn)):
    totp_ativo = totp_db.tem_totp_ativo(conn, user["id_usuario"])
    email_ativo = _tem_2fa_email_ativo(conn, user["id_usuario"])
    email_global = os.getenv("LOGIN_2FA_EMAIL", "true").lower() == "true"
    metodo = "totp" if totp_ativo else ("email" if (email_ativo or email_global) else "nenhum")
    return {
        "totp_ativo": totp_ativo,
        "email_ativo": email_ativo,
        "email_global": email_global,
        "metodo_ativo": metodo,
    }


@router.put("/2fa/preferencia")
def salvar_preferencia_2fa(
    body: Preferencia2FAIn,
    request: Request,
    user=Depends(get_current_user_sem_bloqueio),
    conn=Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notificacao_preferencia (fk_usuario_id_usuario, canal, ativo, nivel_minimo, data_atualizacao)
            VALUES (%s, '2fa_email', %s, 'baixo', now() AT TIME ZONE 'UTC')
            ON CONFLICT (fk_usuario_id_usuario, canal) DO UPDATE
               SET ativo = EXCLUDED.ativo,
                   data_atualizacao = now() AT TIME ZONE 'UTC'
            """,
            (user["id_usuario"], body.email_ativo),
        )
    _audit(conn, user["id_usuario"], "2fa_email_ativado" if body.email_ativo else "2fa_email_desativado", request)
    conn.commit()
    return obter_preferencia_2fa(user=user, conn=conn)


# ---------- login ----------
def _continuar_login(conn, user, request, response, background):
    # Segundo fator por aplicativo autenticador (TOTP): quem cadastrou sempre passa por ele,
    # com ou sem LOGIN_2FA_EMAIL, e o e-mail nunca vale no lugar (evita rebaixar o 2º fator).
    if totp_db.tem_totp_ativo(conn, user["id_usuario"]):
        _audit(conn, user["id_usuario"], "login_senha_ok_aguardando_totp", request)
        conn.commit()
        return {
            "requer_2fa": True,
            "metodo": "totp",
            "expira_em_min": PENDING_MIN,
            "token_temporario": criar_token_2fa(user["id_usuario"]),
        }

    exige_email = (
        os.getenv("LOGIN_2FA_EMAIL", "true").lower() == "true"
        or _tem_2fa_email_ativo(conn, user["id_usuario"])
    )
    if not exige_email:
        sessao = _emitir_sessao(conn, user, request, response)
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

@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, background: BackgroundTasks, conn=Depends(get_conn)):
    email = body.email.strip().lower()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id_usuario, senha AS senha_hash, (status = 'ativo') AS ativo FROM usuario WHERE lower(email) = %s", (email,))
        row = cur.fetchone()

    if row and _bloqueado(conn, row["id_usuario"]):
        _negar_bloqueio(conn, request, row["id_usuario"], "login_bloqueado")

    # sempre roda um verify (mesmo sem usuário) para o tempo de resposta não revelar se o e-mail existe
    senha_ok = verificar_senha(body.senha, row["senha_hash"] if row else DUMMY_HASH)
    if not (row and senha_ok and row["ativo"]):
        _negar(conn, request, row["id_usuario"] if row else None, "login_falha", {"email": email})

    if precisa_rehash(row["senha_hash"]):
        with conn.cursor() as cur:
            cur.execute("UPDATE usuario SET senha = %s WHERE id_usuario = %s",
                        (hash_senha(body.senha), row["id_usuario"]))

    user = carregar_usuario(conn, row["id_usuario"])

    return _continuar_login(conn, user, request, response, background)


@router.post("/ativar-conta")
def ativar_conta(body: AtivarContaIn, request: Request, response: Response, background: BackgroundTasks, conn=Depends(get_conn)):
    email = body.email.strip().lower()
    ip = _ip(request)

    if not body.aceite_termos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"codigo": "TERMOS_NAO_ACEITOS", "mensagem": "É necessário aceitar os Termos e Políticas de Segurança."})
    if body.senha_nova != body.confirmar_senha:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"codigo": "SENHAS_DIFERENTES", "mensagem": "As senhas não coincidem."})
    _exigir_politica(body.senha_nova, email)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM log_acesso
             WHERE acao = 'ativacao_falha' AND ip = %s
               AND data_hora > (now() AT TIME ZONE 'UTC') - interval '1 hour'
            """,
            (ip,),
        )
        if cur.fetchone()[0] >= ATIVACAO_MAX_HORA_IP:
            _negar(conn, request, None, "ativacao_limite", msg="Muitas tentativas. Tente mais tarde.", code=429)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT u.id_usuario, t.id_ativacao, t.codigo_hash, (t.expira_em < now()) AS expirado
              FROM usuario u
              JOIN ativacao_token t ON t.fk_usuario_id_usuario = u.id_usuario
             WHERE lower(u.email) = %s AND u.status = 'pendente' AND t.usado_em IS NULL
             ORDER BY t.criado_em DESC
             LIMIT 1
               FOR UPDATE OF t
            """,
            (email,),
        )
        row = cur.fetchone()

    esperado = hash_token(normalizar_codigo_ativacao(body.codigo))
    if not row or row["expirado"] or not hmac.compare_digest(esperado, row["codigo_hash"]):
        if row:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ativacao_token
                       SET tentativas = tentativas + 1,
                           usado_em = CASE WHEN tentativas + 1 >= %s THEN now() ELSE usado_em END
                     WHERE id_ativacao = %s
                    """,
                    (ATIVACAO_MAX_TENTATIVAS, row["id_ativacao"]),
                )
        _negar(conn, request, row["id_usuario"] if row else None, "ativacao_falha", msg=ATIVACAO_ERRO, code=400)

    id_usuario = row["id_usuario"]
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE usuario
               SET senha = %s, status = 'ativo', ativado_em = now(),
                   termos_aceitos_em = now(), termos_versao = %s, deve_trocar_senha = false
             WHERE id_usuario = %s
            """,
            (hash_senha(body.senha_nova), config.TERMOS_VERSAO, id_usuario),
        )
        cur.execute("UPDATE ativacao_token SET usado_em = now() WHERE fk_usuario_id_usuario = %s AND usado_em IS NULL", (id_usuario,))
        cur.execute("UPDATE refresh_token SET revogado_em = now() WHERE fk_usuario_id_usuario = %s AND revogado_em IS NULL", (id_usuario,))
        cur.execute("UPDATE codigo_2fa_email SET usado_em = now() WHERE fk_usuario_id_usuario = %s AND usado_em IS NULL", (id_usuario,))
    _audit(conn, id_usuario, "conta_ativada", request)

    user = carregar_usuario(conn, id_usuario)
    background.add_task(enviar_aviso_conta_ativada, user["email"], user["nome"])
    return _continuar_login(conn, user, request, response, background)

@router.post("/2fa/reenviar")
def reenviar_codigo(body: TokenTempIn, request: Request, background: BackgroundTasks, conn=Depends(get_conn)):
    user = _usuario_do_token_temporario(conn, body.token_temporario)
    if totp_db.tem_totp_ativo(conn, user["id_usuario"]):
        seguranca_log.bloqueio("OTP", "reenvio_por_email_negado_usuario_usa_totp", user["id_usuario"], ip=_ip(request))
        raise HTTPException(status.HTTP_409_CONFLICT, "Esta conta usa aplicativo autenticador; não há código por e-mail.")
    if _bloqueado(conn, user["id_usuario"]):
        _negar_bloqueio(conn, request, user["id_usuario"], "2fa_bloqueado")

    resultado = _gerar_e_enviar_codigo(conn, user, background)
    if resultado != "enviado":
        msg = "Aguarde um minuto para pedir outro código." if resultado == "cooldown" else "Muitos códigos solicitados. Tente mais tarde."
        _negar(conn, request, user["id_usuario"], "2fa_reenvio_negado", {"motivo": resultado}, msg=msg, code=429)

    _audit(conn, user["id_usuario"], "2fa_codigo_reenviado", request)
    conn.commit()
    return {"email_mascarado": _mascarar(user["email"]), "expira_em_min": CODIGO_VALIDADE_MIN}


@router.post("/2fa/verify")
def verificar_2fa(body: Verify2FAIn, request: Request, response: Response, conn=Depends(get_conn)):
    user = _usuario_do_token_temporario(conn, body.token_temporario)
    if _bloqueado(conn, user["id_usuario"]):
        seguranca_log.bloqueio("OTP", "conta_bloqueada_por_excesso_de_falhas", user["id_usuario"], ip=_ip(request))
        _negar_bloqueio(conn, request, user["id_usuario"], "2fa_bloqueado")

    if totp_db.tem_totp_ativo(conn, user["id_usuario"]):
        metodo = totp_db.verificar_e_consumir(conn, user["id_usuario"], body.codigo)
        if metodo is None:
            # errado, vencido (fora da janela de ±30 s) ou já usado: a resposta é a mesma de propósito
            seguranca_log.bloqueio("OTP", "codigo_recusado(errado_vencido_ou_reutilizado)", user["id_usuario"], ip=_ip(request))
            _negar(conn, request, user["id_usuario"], "2fa_falha", msg="Código inválido")
        sessao = _emitir_sessao(conn, user, request, response)
        _audit(conn, user["id_usuario"], "login_ok_2fa_recuperacao" if metodo == "recuperacao" else "login_ok_2fa_totp", request)
        conn.commit()
        return sessao

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
    sessao = _emitir_sessao(conn, user, request, response)
    _audit(conn, user["id_usuario"], "login_ok_2fa", request, {"metodo": "email"})
    conn.commit()
    return sessao


# ---------- refresh / logout ----------
@router.post("/refresh")
def refresh(request: Request, response: Response, body: RefreshIn | None = None, conn=Depends(get_conn)):
    """Troca o refresh token (cookie) por um novo access token. O front chama isto ao abrir o app."""
    raw = request.cookies.get(COOKIE_REFRESH)
    if raw:
        _checar_origem(request)
    elif body and body.refresh_token:   # compatibilidade com clientes que ainda mandam no corpo
        raw = body.refresh_token
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sem sessão")
    h = hash_token(raw)
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
    sessao = _emitir_sessao(conn, user, request, response, familia=rt["familia"])
    conn.commit()
    return sessao


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, body: RefreshIn | None = None, conn=Depends(get_conn)):
    raw = request.cookies.get(COOKIE_REFRESH) or (body.refresh_token if body else None)
    _limpar_cookie_refresh(response)
    if not raw:
        return
    if request.cookies.get(COOKIE_REFRESH):
        _checar_origem(request)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE refresh_token SET revogado_em = now()
             WHERE familia = (SELECT familia FROM refresh_token WHERE token_hash = %s)
               AND revogado_em IS NULL
            RETURNING fk_usuario_id_usuario
            """,
            (hash_token(raw),),
        )
        r = cur.fetchone()
    if r:
        _audit(conn, r[0], "logout", request)
    conn.commit()


@router.get("/me")
def quem_sou_eu(user=Depends(get_current_user_sem_bloqueio)):
    return {
        "id_usuario": user["id_usuario"],
        "nome": user["nome"],
        "email": user["email"],
        "perfil": user["perfil"],
        "deve_trocar_senha": user["deve_trocar_senha"],
    }


# ---------- trocar senha (usuário logado) ----------
@router.post("/trocar-senha", status_code=status.HTTP_204_NO_CONTENT)
def trocar_senha(body: TrocarSenhaIn, request: Request, background: BackgroundTasks,
                 user=Depends(get_current_user_sem_bloqueio), conn=Depends(get_conn)):
    """Exige a senha atual (um token de acesso roubado não basta para tomar a conta)."""
    id_usuario = user["id_usuario"]
    if _bloqueado(conn, id_usuario):
        _negar_bloqueio(conn, request, id_usuario, "trocar_senha_bloqueado")

    with conn.cursor() as cur:
        cur.execute("SELECT senha FROM usuario WHERE id_usuario = %s", (id_usuario,))
        hash_atual = cur.fetchone()[0]
    if not verificar_senha(body.senha_atual, hash_atual or DUMMY_HASH):
        _negar(conn, request, id_usuario, "senha_atual_falha", msg="Senha atual incorreta", code=403)
    if body.senha_nova == body.senha_atual:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A nova senha deve ser diferente da atual")
    _exigir_politica(body.senha_nova, user["email"])

    with conn.cursor() as cur:
        cur.execute("UPDATE usuario SET senha = %s, deve_trocar_senha = false WHERE id_usuario = %s",
                    (hash_senha(body.senha_nova), id_usuario))
    # derruba as outras sessões e mantém só a deste navegador (se o cookie veio; sem ele, derruba todas)
        cur.execute(
            """
            UPDATE refresh_token SET revogado_em = now()
             WHERE fk_usuario_id_usuario = %s AND revogado_em IS NULL
               AND familia IS DISTINCT FROM (SELECT familia FROM refresh_token WHERE token_hash = %s)
            """,
            (id_usuario, hash_token(request.cookies.get(COOKIE_REFRESH, ""))),
        )
    _audit(conn, id_usuario, "senha_trocada", request)
    conn.commit()
    background.add_task(enviar_aviso_senha_alterada, user["email"], user["nome"])


# ---------- recuperar senha (usuário deslogado) ----------
@router.post("/esqueci-senha")
def esqueci_senha(body: EsqueciSenhaIn, request: Request, background: BackgroundTasks, conn=Depends(get_conn)):
    """Resposta idêntica exista o e-mail ou não (não revela quem tem conta)."""
    email = body.email.strip().lower()
    ip = _ip(request)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT count(*) AS n FROM log_acesso
             WHERE acao = 'reset_solicitado' AND ip = %s
               AND data_hora > (now() AT TIME ZONE 'UTC') - interval '1 hour'
            """,
            (ip,),
        )
        if cur.fetchone()["n"] >= RESET_MAX_HORA_IP:
            return RESET_RESPOSTA
        cur.execute("SELECT id_usuario FROM usuario WHERE lower(email) = %s AND status = 'ativo'", (email,))
        row = cur.fetchone()
    # registra mesmo quando o e-mail não existe, para o limite por IP valer contra varredura de e-mails
    _audit(conn, row["id_usuario"] if row else None, "reset_solicitado", request)

    if row:
        user = carregar_usuario(conn, row["id_usuario"])
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM senha_reset_token WHERE fk_usuario_id_usuario = %s AND criado_em > now() - interval '1 hour'",
                (user["id_usuario"],),
            )
            if cur.fetchone()[0] < RESET_MAX_HORA_USUARIO:
                # só o link mais novo vale
                cur.execute(
                    "UPDATE senha_reset_token SET usado_em = now() WHERE fk_usuario_id_usuario = %s AND usado_em IS NULL",
                    (user["id_usuario"],),
                )
                raw = secrets.token_urlsafe(32)
                cur.execute(
                    """
                    INSERT INTO senha_reset_token (fk_usuario_id_usuario, token_hash, expira_em, ip)
                    VALUES (%s, %s, now() + make_interval(mins => %s), %s)
                    """,
                    (user["id_usuario"], hash_token(raw), RESET_VALIDADE_MIN, ip),
                )
                link = f"{FRONTEND_URL}/redefinir-senha?token={raw}"
                background.add_task(enviar_link_reset_senha, user["email"], user["nome"], link, RESET_VALIDADE_MIN)
    conn.commit()
    return RESET_RESPOSTA


@router.post("/redefinir-senha")
def redefinir_senha(body: RedefinirSenhaIn, request: Request, background: BackgroundTasks, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id_reset, fk_usuario_id_usuario, usado_em, (expira_em < now()) AS expirado
              FROM senha_reset_token WHERE token_hash = %s FOR UPDATE
            """,
            (hash_token(body.token),),
        )
        rt = cur.fetchone()

    user = carregar_usuario(conn, rt["fk_usuario_id_usuario"]) if rt else None
    if not rt or rt["usado_em"] or rt["expirado"] or not user or not user["ativo"]:
        _negar(conn, request, rt["fk_usuario_id_usuario"] if rt else None, "reset_falha",
               msg="Link inválido ou expirado. Peça um novo.", code=400)
    _exigir_politica(body.senha_nova, user["email"])

    with conn.cursor() as cur:
        cur.execute("UPDATE usuario SET senha = %s, deve_trocar_senha = false WHERE id_usuario = %s",
                    (hash_senha(body.senha_nova), user["id_usuario"]))
        cur.execute("UPDATE senha_reset_token SET usado_em = now() WHERE fk_usuario_id_usuario = %s AND usado_em IS NULL",
                    (user["id_usuario"],))
        # senha nova => códigos 2FA pendentes deixam de valer; as sessões só caem se desconectar_outros
        if body.desconectar_outros:
            cur.execute("UPDATE refresh_token SET revogado_em = now() WHERE fk_usuario_id_usuario = %s AND revogado_em IS NULL",
                        (user["id_usuario"],))
        cur.execute("UPDATE codigo_2fa_email SET usado_em = now() WHERE fk_usuario_id_usuario = %s AND usado_em IS NULL",
                    (user["id_usuario"],))
    _audit(conn, user["id_usuario"], "senha_redefinida", request)
    conn.commit()
    background.add_task(enviar_aviso_senha_alterada, user["email"], user["nome"])
    # sem login automático: o usuário entra pelo fluxo normal (senha + 2FA)
    return {"mensagem": "Senha redefinida. Entre com a nova senha."}