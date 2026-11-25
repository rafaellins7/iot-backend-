from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from src.api.deps import get_conn
from src.api.deps_auth import get_current_user
from src.api.escopo import exigir_sensor, filtrar_leituras_por_dono, id_dono, nao_encontrado
from src.api.filtros import clausula, montar_where
from src.api.schemas import LeituraRejeitadaOut

router = APIRouter(prefix="/leituras-rejeitadas", tags=["leituras-rejeitadas"])

SELECT_BASE = """
    SELECT id_rejeicao, fk_sensor_id_sensor AS id_sensor, entry_id_thingspeak,
           temperatura_bruta, umidade_bruta, data_hora_bruta, motivo, origem,
           data_rejeicao
    FROM leitura_rejeitada
"""


@router.get("", response_model=List[LeituraRejeitadaOut])
def listar_leituras_rejeitadas(
    id_sensor: Optional[int] = None,
    motivo: Optional[str] = Query(None, description="Trecho do motivo (ex.: 'fora da faixa')"),
    inicio: Optional[datetime] = Query(None, description="Rejeitadas a partir desta data/hora"),
    fim: Optional[datetime] = Query(None, description="Rejeitadas até esta data/hora"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    where, params = [], []
    if id_sensor is not None:
        where.append("fk_sensor_id_sensor = %s")
        params.append(id_sensor)
    if motivo:
        where.append("motivo ILIKE %s")
        params.append(f"%{motivo}%")
    montar_where("data_rejeicao", inicio, fim, where, params)
    filtrar_leituras_por_dono(user, "fk_sensor_id_sensor", where, params)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        exigir_sensor(cur, user, id_sensor)
        cur.execute(
            SELECT_BASE + clausula(where) + " ORDER BY data_rejeicao DESC, id_rejeicao DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        return cur.fetchall()


@router.get("/{id_rejeicao}", response_model=LeituraRejeitadaOut)
def obter_leitura_rejeitada(id_rejeicao: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            SELECT_BASE + " WHERE id_rejeicao = %s AND (%s::int IS NULL OR fk_sensor_id_sensor IN"
            " (SELECT id_sensor FROM sensor WHERE fk_usuario_id_usuario = %s))",
            (id_rejeicao, id_dono(user), id_dono(user)),
        )
        registro = cur.fetchone()
    if registro is None:
        raise nao_encontrado(user, "leitura_rejeitada", id_rejeicao, "Registro de rejeição não encontrado")
    return registro