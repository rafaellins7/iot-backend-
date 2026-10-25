from typing import List, Optional

from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from src.api.deps import get_conn

router = APIRouter(prefix="/ia", tags=["ia"])


class ModeloOut(BaseModel):
    id_modelo: int
    nome: str
    tipo_modelo: str
    finalidade: str
    algoritmo: Optional[str] = None
    versao: Optional[str] = None
    status: str
    data_criacao: Optional[str] = None
    data_atualizacao: Optional[str] = None


@router.get("/modelos", response_model=List[ModeloOut])
def listar_modelos(status: Optional[str] = None, conn=Depends(get_conn)):
    sql = "SELECT * FROM ia_modelo"
    args = ()
    if status:
        sql += " WHERE status = %s"
        args = (status,)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql + " ORDER BY id_modelo", args)
        linhas = cur.fetchall()
    for r in linhas:
        for k in ("data_criacao", "data_atualizacao"):
            r[k] = r[k].isoformat() if r[k] else None
    return linhas