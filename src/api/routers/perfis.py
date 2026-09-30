from typing import List

from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from src.api.deps import get_conn
from src.api.schemas import PerfilOut

router = APIRouter(prefix="/perfis", tags=["perfis"])


@router.get("", response_model=List[PerfilOut])
def listar_perfis(conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id_perfil, nome, descricao FROM perfil ORDER BY id_perfil")
        return cur.fetchall()