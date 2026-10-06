from datetime import datetime, timedelta, timezone
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from src import config
from src.api.deps import get_conn

router = APIRouter(prefix="/sensores", tags=["sensores"])


class Periodo(str, Enum):
    h24 = "24h"
    d7 = "7d"
    d30 = "30d"


# seletor do dashboard -> (janela, agregação)
REGRAS = {
    Periodo.h24: (timedelta(hours=24), "hora"),
    Periodo.d7: (timedelta(days=7), "hora"),
    Periodo.d30: (timedelta(days=30), "dia"),
}


def _iso_utc(dt: datetime) -> str:
    """Devolve ISO 8601 com 'Z' (o banco guarda UTC sem fuso)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/{id_sensor}/leituras")
def leituras_agregadas(id_sensor: int, periodo: Periodo = Periodo.h24, conn=Depends(get_conn)):
    janela, agregacao = REGRAS[periodo]
    fim = datetime.now(timezone.utc).replace(tzinfo=None)
    inicio = fim - janela

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT ambiente FROM sensor WHERE id_sensor = %s", (id_sensor,))
        sensor = cur.fetchone()
        if sensor is None:
            raise HTTPException(status_code=404, detail="Sensor não encontrado")

        if agregacao == "hora":
            instante_sql, params_inst = "date_trunc('hour', l.data_hora)", []
        else:
            # dia civil no fuso do projeto (America/Recife); devolve a meia-noite local
            instante_sql = ("date_trunc('day', (l.data_hora AT TIME ZONE 'UTC') AT TIME ZONE %s)"
                            " AT TIME ZONE %s")
            params_inst = [config.CLIMA_TIMEZONE, config.CLIMA_TIMEZONE]

        cur.execute(
            f"""
            SELECT {instante_sql} AS instante,
                   ROUND(AVG(l.temperatura)::numeric, 2) AS temperatura,
                   ROUND(AVG(l.umidade)::numeric, 2)     AS umidade,
                   COUNT(*)::int                         AS n_leituras,
                   bool_and(lower(COALESCE(l.origem, '')) = 'thingspeak') AS todas_reais
            FROM leitura_climatica l
            WHERE l.fk_sensor_id_sensor = %s AND l.data_hora >= %s AND l.data_hora <= %s
            GROUP BY 1
            ORDER BY 1
            """,
            params_inst + [id_sensor, inicio, fim],
        )
        linhas = cur.fetchall()

    return {
        "id_sensor": id_sensor,
        "ambiente": sensor["ambiente"],
        "periodo": periodo.value,
        "agregacao": agregacao,
        "pontos": [
            {
                "instante": _iso_utc(r["instante"]),
                "temperatura": float(r["temperatura"]) if r["temperatura"] is not None else None,
                "umidade": float(r["umidade"]) if r["umidade"] is not None else None,
                "n_leituras": r["n_leituras"],
                "origem": "real" if r["todas_reais"] else "simulado",
            }
            for r in linhas
        ],
    }