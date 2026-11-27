from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from psycopg2.extras import RealDictCursor

from . import seguranca_log
from .deps import get_conn
from .security_auth import decodificar

bearer = HTTPBearer(auto_error=False)

ADMIN = "Administrador"
ANALISTA = "Analista de Dados"
PRODUTOR_EXPORTADOR = "Produtor/Exportador"


def carregar_usuario(conn, id_usuario: int) -> dict | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT u.id_usuario, u.nome, u.email, u.deve_trocar_senha, (u.status = 'ativo') AS ativo, p.nome AS perfil
              FROM usuario u
              JOIN perfil p ON p.id_perfil = u.fk_perfil_id_perfil
             WHERE u.id_usuario = %s
            """,
            (id_usuario,),
        )
        return cur.fetchone()


def get_current_user_sem_bloqueio(cred=Depends(bearer), conn=Depends(get_conn)):
    if cred is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Não autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decodificar(cred.credentials, "access")
    user = carregar_usuario(conn, int(payload["sub"]))
    # consulta por PK a cada request: desativar um usuário vale na hora, sem esperar o JWT expirar
    if not user or not user["ativo"]:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Usuário inativo ou inexistente",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def get_current_user(cred=Depends(bearer), conn=Depends(get_conn)):
    user = get_current_user_sem_bloqueio(cred, conn)
    if user["deve_trocar_senha"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"codigo": "TROCA_SENHA_OBRIGATORIA", "mensagem": "É necessário trocar a senha antes de continuar."},
        )
    return user


def _eh_admin(user) -> bool:
    """O Administrador passa em qualquer regra, sem precisar ser listado."""
    return user["perfil"].lower() == ADMIN.lower()


def require_role(*perfis: str):
    permitidos = {p.lower() for p in perfis}

    def dependencia(user=Depends(get_current_user)):
        if _eh_admin(user) or user["perfil"].lower() in permitidos:
            return user
        seguranca_log.bloqueio("IDOR", "perfil_sem_permissao_no_recurso", user["id_usuario"], perfil=user["perfil"])
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Perfil sem permissão para este recurso")

    return dependencia


METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


def require_role_por_metodo(*, leitura: tuple, escrita: tuple, exclusao: tuple | None = None):
    """Permissão que depende do método HTTP.
    leitura  -> GET/HEAD/OPTIONS
    escrita  -> POST/PUT/PATCH
    exclusao -> DELETE (se omitido, usa 'escrita')
    """
    por_tipo = {
        "leitura": {p.lower() for p in leitura},
        "escrita": {p.lower() for p in escrita},
        "exclusao": {p.lower() for p in (exclusao if exclusao is not None else escrita)},
    }

    def dependencia(request: Request, user=Depends(get_current_user)):
        if request.method in METODOS_SEGUROS:
            permitidos = por_tipo["leitura"]
        elif request.method == "DELETE":
            permitidos = por_tipo["exclusao"]
        else:
            permitidos = por_tipo["escrita"]
        if _eh_admin(user) or user["perfil"].lower() in permitidos:
            return user
        seguranca_log.bloqueio("IDOR", "perfil_sem_permissao_para_o_metodo", user["id_usuario"],
                               metodo=request.method, rota=request.url.path)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Perfil sem permissão para este recurso")

    return dependencia