from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from src.api.deps import get_conn
from src.api.filtros import clausula, garantir_sensor, montar_where

router = APIRouter(prefix="/relatorios", tags=["relatorios"])

Agrupamento = Literal["dia", "semana", "mes"]
_UNIDADE_TRUNC = {"dia": "day", "semana": "week", "mes": "month"}


class SaidaFaixaOut(BaseModel):
    periodo: datetime
    total_leituras: int
    saidas_faixa: int
    saidas_temperatura: int
    saidas_umidade: int
    pct_fora: Optional[float] = None


# Reproduz o mesmo casamento leitura -> faixa usado pelo trigger trg_alerta_faixa e pela view , 
# caindo em 'armazenamento' quando a etapa for transporte' e não houver faixa própria para transporte.

_LEITURAS_AVALIADAS = """
    SELECT l.id_leitura, l.data_hora, lo.id_lote,
           (l.temperatura < c.temp_min OR l.temperatura > c.temp_max) AS temp_fora,
           (l.umidade < c.umidade_min OR l.umidade > c.umidade_max) AS umid_fora
    FROM leitura_climatica l
    JOIN sensor s ON s.id_sensor = l.fk_sensor_id_sensor
    JOIN lote lo ON lo.id_lote = s.fk_lote_id_lote
    JOIN LATERAL (
        SELECT c.* FROM config_parametro c
        WHERE c.fk_fruta_id_fruta = lo.fk_fruta_id_fruta
          AND (c.etapa = fn_etapa_lote(lo.status)
               OR (fn_etapa_lote(lo.status) = 'transporte' AND c.etapa = 'armazenamento'))
        ORDER BY (c.etapa = fn_etapa_lote(lo.status)) DESC
        LIMIT 1
    ) c ON TRUE
"""


@router.get("/saidas-faixa", response_model=List[SaidaFaixaOut])
def saidas_faixa(
    agrupamento: Agrupamento = "semana",
    id_lote: Optional[int] = None,
    id_sensor: Optional[int] = None,
    inicio: Optional[datetime] = Query(None, description="Data/hora inicial (ISO 8601, UTC se sem fuso)"),
    fim: Optional[datetime] = Query(None, description="Data/hora final (ISO 8601, UTC se sem fuso)"),
    conn=Depends(get_conn),
):
    """Contagem de leituras fora da faixa ideal (temperatura e/ou umidade), agrupada
    por período. Só entram leituras de lotes com fruta e etapa configuradas em
    config_parametro — sem faixa cadastrada, não há como avaliar e a leitura fica de fora."""
    where, params = [], []
    if id_lote is not None:
        where.append("lo.id_lote = %s")
        params.append(id_lote)
    if id_sensor is not None:
        where.append("s.id_sensor = %s")
        params.append(id_sensor)
    montar_where("l.data_hora", inicio, fim, where, params)

    sql = f"""
        WITH leituras_avaliadas AS ({_LEITURAS_AVALIADAS + clausula(where)})
        SELECT date_trunc(%s, data_hora) AS periodo,
               COUNT(*)::int AS total_leituras,
               COUNT(*) FILTER (WHERE temp_fora OR umid_fora)::int AS saidas_faixa,
               COUNT(*) FILTER (WHERE temp_fora)::int AS saidas_temperatura,
               COUNT(*) FILTER (WHERE umid_fora)::int AS saidas_umidade
        FROM leituras_avaliadas
        GROUP BY periodo
        ORDER BY periodo
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        garantir_sensor(cur, id_sensor)
        cur.execute(sql, params + [_UNIDADE_TRUNC[agrupamento]])
        linhas = cur.fetchall()

    for linha in linhas:
        linha["pct_fora"] = (
            round(100 * linha["saidas_faixa"] / linha["total_leituras"], 1)
            if linha["total_leituras"] else None
        )
    return linhas