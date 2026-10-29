from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from psycopg2.extras import RealDictCursor

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
            SELECT u.id_usuario, u.nome, u.email, (u.status = 'ativo') AS ativo, p.nome AS perfil
              FROM usuario u
              JOIN perfil p ON p.id_perfil = u.fk_perfil_id_perfil
             WHERE u.id_usuario = %s
            """,
            (id_usuario,),
        )
        return cur.fetchone()


def get_current_user(cred=Depends(bearer), conn=Depends(get_conn)):
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


def require_role(*perfis: str):
    permitidos = {p.lower() for p in perfis}

    def dependencia(user=Depends(get_current_user)):
        if user["perfil"].lower() not in permitidos:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Perfil sem permissão para este recurso")
        return user

    return dependencia