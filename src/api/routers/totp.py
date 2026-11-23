"""Cadastro e gestão do 2º fator por aplicativo autenticador (TOTP). Todas as rotas exigem login."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .. import seguranca_log, totp, totp_db
from ..deps import get_conn
from ..deps_auth import get_current_user
from ..security_auth import DUMMY_HASH, verificar_senha
from .auth import _audit, _bloqueado, _ip, _negar, _negar_bloqueio

router = APIRouter(prefix="/auth/2fa/totp", tags=["2fa-totp"])


class CodigoIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=32)


class DesativarIn(BaseModel):
    senha: str = Field(min_length=1, max_length=128)
    codigo: str = Field(min_length=1, max_length=32)


def _checar_bloqueio(conn, request, user):
    if _bloqueado(conn, user["id_usuario"]):
        seguranca_log.bloqueio("OTP", "conta_bloqueada_por_excesso_de_falhas", user["id_usuario"], ip=_ip(request))
        _negar_bloqueio(conn, request, user["id_usuario"], "2fa_bloqueado")


@router.get("/status")
def status_totp(user=Depends(get_current_user), conn=Depends(get_conn)):
    ativo = totp_db.tem_totp_ativo(conn, user["id_usuario"])
    return {"ativo": ativo, "codigos_recuperacao_restantes": totp_db.restantes_recuperacao(conn, user["id_usuario"]) if ativo else 0}


@router.post("/iniciar")
def iniciar(request: Request, user=Depends(get_current_user), conn=Depends(get_conn)):
    """Gera o segredo e devolve o QR Code. Só vale depois de /confirmar."""
    if totp_db.tem_totp_ativo(conn, user["id_usuario"]):
        raise HTTPException(status.HTTP_409_CONFLICT, "O aplicativo autenticador já está ativo. Desative antes de cadastrar outro.")
    segredo = totp.novo_segredo()
    totp_db.iniciar_cadastro(conn, user["id_usuario"], segredo)
    _audit(conn, user["id_usuario"], "totp_cadastro_iniciado", request)
    conn.commit()
    uri = totp.uri_otpauth(segredo, user["email"])
    return {
        "otpauth_uri": uri,
        "qr_code_png_base64": totp.qr_png_base64(uri),   # <img src="data:image/png;base64,...">
        "segredo_manual": segredo,                        # para digitar no app se não der para ler o QR
        "digitos": totp.DIGITOS,
        "periodo_s": totp.PERIODO_S,
    }


@router.post("/confirmar")
def confirmar(body: CodigoIn, request: Request, user=Depends(get_current_user), conn=Depends(get_conn)):
    """Confere o 1º código do app, ativa o TOTP e entrega os códigos de recuperação (só desta vez)."""
    _checar_bloqueio(conn, request, user)
    codigos = totp_db.confirmar_cadastro(conn, user["id_usuario"], body.codigo)
    if codigos is None:
        seguranca_log.bloqueio("OTP", "confirmacao_de_cadastro_recusada", user["id_usuario"], ip=_ip(request))
        _negar(conn, request, user["id_usuario"], "2fa_falha", msg="Código inválido ou cadastro não iniciado", code=400)
    _audit(conn, user["id_usuario"], "totp_ativado", request)
    conn.commit()
    return {"ativo": True, "codigos_recuperacao": codigos,
            "aviso": "Guarde estes códigos agora: cada um vale uma única vez e não serão mostrados de novo."}


@router.post("/recuperacao/regenerar")
def regenerar(body: CodigoIn, request: Request, user=Depends(get_current_user), conn=Depends(get_conn)):
    """Troca o conjunto de códigos de recuperação (os antigos deixam de valer). Exige código do app."""
    _checar_bloqueio(conn, request, user)
    if totp_db.verificar_e_consumir(conn, user["id_usuario"], body.codigo, aceitar_recuperacao=False) != "totp":
        seguranca_log.bloqueio("OTP", "regeneracao_de_recuperacao_recusada", user["id_usuario"], ip=_ip(request))
        _negar(conn, request, user["id_usuario"], "2fa_falha", msg="Código inválido", code=403)
    codigos = totp_db.regenerar_recuperacao(conn, user["id_usuario"])
    _audit(conn, user["id_usuario"], "totp_recuperacao_regenerada", request)
    conn.commit()
    return {"codigos_recuperacao": codigos}


@router.post("/desativar", status_code=status.HTTP_204_NO_CONTENT)
def desativar(body: DesativarIn, request: Request, user=Depends(get_current_user), conn=Depends(get_conn)):
    """Exige senha E código atual (um token de acesso roubado não basta para tirar o 2º fator)."""
    _checar_bloqueio(conn, request, user)
    with conn.cursor() as cur:
        cur.execute("SELECT senha FROM usuario WHERE id_usuario = %s", (user["id_usuario"],))
        hash_atual = cur.fetchone()[0]
    senha_ok = verificar_senha(body.senha, hash_atual or DUMMY_HASH)
    metodo = totp_db.verificar_e_consumir(conn, user["id_usuario"], body.codigo) if senha_ok else None
    if not metodo:
        seguranca_log.bloqueio("OTP", "desativacao_recusada", user["id_usuario"], ip=_ip(request))
        _negar(conn, request, user["id_usuario"], "2fa_falha", msg="Senha ou código inválido", code=403)
    totp_db.desativar(conn, user["id_usuario"])
    _audit(conn, user["id_usuario"], "totp_desativado", request)
    conn.commit()
