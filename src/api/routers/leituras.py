from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from src.api.deps import get_conn
from src.api.filtros import clausula, garantir_sensor, montar_where
from src.api.schemas import EstatisticasLeituraOut, LeituraOut

router = APIRouter(prefix="/leituras", tags=["leituras"])

SELECT_BASE = """
    SELECT id_leitura, fk_sensor_id_sensor AS id_sensor, temperatura, umidade,
           data_hora, data_recebimento, origem, entry_id_thingspeak
    FROM leitura_climatica
"""


def _filtros(id_sensor: Optional[int], inicio: Optional[datetime], fim: Optional[datetime]):
    where, params = [], []
    if id_sensor is not None:
        where.append("fk_sensor_id_sensor = %s")
        params.append(id_sensor)
    montar_where("data_hora", inicio, fim, where, params)
    return clausula(where), params


@router.get("", response_model=List[LeituraOut])
def listar_leituras(
    id_sensor: Optional[int] = None,
    inicio: Optional[datetime] = Query(None, description="Data/hora inicial (ISO 8601, UTC se sem fuso)"),
    fim: Optional[datetime] = Query(None, description="Data/hora final (ISO 8601, UTC se sem fuso)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    where_sql, params = _filtros(id_sensor, inicio, fim)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        garantir_sensor(cur, id_sensor)
        cur.execute(
            SELECT_BASE + where_sql + " ORDER BY data_hora DESC, id_leitura DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        return cur.fetchall()

@router.get("/ultima", response_model=LeituraOut)
def ultima_leitura(id_sensor: Optional[int] = None, conn=Depends(get_conn)):
    where_sql, params = _filtros(id_sensor, None, None)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        garantir_sensor(cur, id_sensor)
        cur.execute(
            SELECT_BASE + where_sql + " ORDER BY data_hora DESC, id_leitura DESC LIMIT 1", params
        )
        leitura = cur.fetchone()
    if leitura is None:
        raise HTTPException(status_code=404, detail="Nenhuma leitura encontrada")
    return leitura


@router.get("/estatisticas", response_model=EstatisticasLeituraOut)
def estatisticas_leituras(
    id_sensor: Optional[int] = None,
    inicio: Optional[datetime] = None,
    fim: Optional[datetime] = None,
    conn=Depends(get_conn),
):
    where_sql, params = _filtros(id_sensor, inicio, fim)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        garantir_sensor(cur, id_sensor)
        cur.execute(
            f"""
            SELECT COUNT(*)::int                               AS total_leituras,
                   MIN(data_hora)                              AS primeira_leitura,
                   MAX(data_hora)                              AS ultima_leitura,
                   MIN(temperatura)                            AS temperatura_min,
                   MAX(temperatura)                            AS temperatura_max,
                   ROUND(AVG(temperatura)::numeric, 2)         AS temperatura_media,
                   MIN(umidade)                                AS umidade_min,
                   MAX(umidade)                                AS umidade_max,
                   ROUND(AVG(umidade)::numeric, 2)             AS umidade_media
            FROM leitura_climatica{where_sql}
            """,
            params,
        )
        return cur.fetchone()


@router.get("/{id_leitura}", response_model=LeituraOut)
def obter_leitura(id_leitura: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(SELECT_BASE + " WHERE id_leitura = %s", (id_leitura,))
        leitura = cur.fetchone()
    if leitura is None:
        raise HTTPException(status_code=404, detail="Leitura não encontrada")
    return leitura