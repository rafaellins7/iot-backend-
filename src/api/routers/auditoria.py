from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from src.api.deps import get_conn
from src.api.filtros import clausula, montar_where
from src.api.schemas import LogAuditoriaOut

router = APIRouter(prefix="/auditoria", tags=["auditoria"])

SELECT_BASE = """
    SELECT l.id_log, l.data_hora, l.acao, l.ip::text AS ip, l.resultado,
           l.fk_usuario_id_usuario AS id_usuario, u.nome AS usuario
    FROM log_acesso l
    LEFT JOIN usuario u ON u.id_usuario = l.fk_usuario_id_usuario
"""


@router.get("", response_model=List[LogAuditoriaOut])
def listar_logs(
    id_usuario: Optional[int] = None,
    acao: Optional[str] = Query(None, description="Trecho da ação (ex.: 'criar_usuario')"),
    resultado: Optional[str] = Query(None, description="Trecho do resultado (ex.: 'falha')"),
    inicio: Optional[datetime] = None,
    fim: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    where, params = [], []
    if id_usuario is not None:
        where.append("l.fk_usuario_id_usuario = %s")
        params.append(id_usuario)
    if acao:
        where.append("l.acao ILIKE %s")
        params.append(f"%{acao}%")
    if resultado:
        where.append("l.resultado ILIKE %s")
        params.append(f"%{resultado}%")
    montar_where("l.data_hora", inicio, fim, where, params)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            SELECT_BASE + clausula(where) + " ORDER BY l.data_hora DESC, l.id_log DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        return cur.fetchall()


@router.get("/{id_log}", response_model=LogAuditoriaOut)
def obter_log(id_log: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(SELECT_BASE + " WHERE l.id_log = %s", (id_log,))
        registro = cur.fetchone()
    if registro is None:
        raise HTTPException(status_code=404, detail="Registro de auditoria não encontrado")
    return registro