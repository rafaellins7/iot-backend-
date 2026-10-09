from datetime import timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from src.api.deps import get_conn

router = APIRouter(prefix="/alertas", tags=["alertas"])

# Sensor e lote do alerta vem pela leitura que o gerou (alerta preditivo: sem sensor/lote).
SELECT_BASE = """
    SELECT a.id_alerta, a.tipo_alerta, a.descricao, a.nivel::text AS nivel,
           a.status, a.data_hora,
           a.fk_leitura_id_leitura AS id_leitura,
           a.fk_previsao_id_previsao AS id_previsao,
           s.id_sensor, s.fk_lote_id_lote AS id_lote
    FROM alerta a
    LEFT JOIN leitura_climatica r ON r.id_leitura = a.fk_leitura_id_leitura
    LEFT JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
"""


class AlertaOut(BaseModel):
    id_alerta: int
    tipo_alerta: Optional[str] = None
    descricao: Optional[str] = None
    nivel: Optional[str] = None
    status: Optional[str] = None
    data_hora: Optional[str] = None   # ISO 8601 com Z (o banco guarda UTC sem fuso)
    id_leitura: Optional[int] = None
    id_previsao: Optional[int] = None
    id_sensor: Optional[int] = None
    id_lote: Optional[int] = None


class AlertaStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=50)


def _saida(linha: dict) -> dict:
    dt = linha.get("data_hora")
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        linha["data_hora"] = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return linha


@router.get("", response_model=List[AlertaOut])
def listar_alertas(
    status: Optional[str] = None,
    nivel: Optional[str] = None,
    id_sensor: Optional[int] = None,
    id_lote: Optional[int] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    where, params = [], []
    if status:
        where.append("lower(a.status) = lower(%s)")
        params.append(status)
    if nivel:
        where.append("a.nivel::text = %s")
        params.append(nivel)
    if id_sensor is not None:
        where.append("s.id_sensor = %s")
        params.append(id_sensor)
    if id_lote is not None:
        where.append("s.fk_lote_id_lote = %s")
        params.append(id_lote)
    sql = (SELECT_BASE
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY a.data_hora DESC, a.id_alerta DESC LIMIT %s OFFSET %s")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params + [limit, offset])
        return [_saida(r) for r in cur.fetchall()]


@router.get("/{id_alerta}", response_model=AlertaOut)
def obter_alerta(id_alerta: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(SELECT_BASE + " WHERE a.id_alerta = %s", (id_alerta,))
        linha = cur.fetchone()
    if linha is None:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")
    return _saida(linha)


@router.patch("/{id_alerta}/status", response_model=AlertaOut)
def atualizar_status_alerta(id_alerta: int, dados: AlertaStatusUpdate, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "UPDATE alerta SET status = %s WHERE id_alerta = %s RETURNING id_alerta",
            (dados.status.strip().lower(), id_alerta),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Alerta não encontrado")
        cur.execute(SELECT_BASE + " WHERE a.id_alerta = %s", (id_alerta,))
        linha = cur.fetchone()
    conn.commit()
    return _saida(linha)