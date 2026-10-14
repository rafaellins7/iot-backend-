from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from src.api.deps import get_conn

router = APIRouter(prefix="/frutas", tags=["frutas"])


class FrutaOut(BaseModel):
    id_fruta: int
    nome: Optional[str] = None


SELECT_BASE = "SELECT id_fruta, nome FROM fruta"


@router.get("", response_model=List[FrutaOut])
def listar_frutas(nome: Optional[str] = None, conn=Depends(get_conn)):
    """Listagem simples, usada para preencher os formulários de lote e de faixa (config-parametros)."""
    sql = SELECT_BASE
    params = []
    if nome:
        sql += " WHERE nome ILIKE %s"
        params.append(f"%{nome}%")
    sql += " ORDER BY nome"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@router.get("/{id_fruta}", response_model=FrutaOut)
def obter_fruta(id_fruta: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(SELECT_BASE + " WHERE id_fruta = %s", (id_fruta,))
        fruta = cur.fetchone()
    if fruta is None:
        raise HTTPException(status_code=404, detail="Fruta não encontrada")
    return fruta