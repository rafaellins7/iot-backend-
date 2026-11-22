"""Endpoints da tela Rede ESP32: histórico de ingestão/PDR e sincronização manual ThingSpeak."""
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from src import database, thingspeak_client
from src.api.deps import get_conn
from src.api.deps_auth import ADMIN, ANALISTA, require_role

router = APIRouter(tags=["rede"])

permissao_analista = [Depends(require_role(ANALISTA, ADMIN))]


@router.get("/rede/historico", dependencies=permissao_analista)
def historico_rede(
    periodo: str = Query("24h", pattern="^(24h|7d)$"),
    conn=Depends(get_conn),
):
    """Agrega leituras aceitas vs rejeitadas por hora (24h) ou dia (7d) para o gráfico de disponibilidade/PDR."""
    if periodo == "7d":
        trunc_unit = "day"
        intervalo = "7 days"
    else:
        trunc_unit = "hour"
        intervalo = "24 hours"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            WITH aceitas AS (
                SELECT date_trunc('{trunc_unit}', data_hora) AS bucket,
                       COUNT(*)::int AS gravadas
                  FROM leitura_climatica
                 WHERE data_hora >= (now() AT TIME ZONE 'UTC') - interval '{intervalo}'
                 GROUP BY 1
            ),
            rejeitadas AS (
                SELECT date_trunc('{trunc_unit}', data_rejeicao) AS bucket,
                       COUNT(*)::int AS rejeitadas
                  FROM leitura_rejeitada
                 WHERE data_rejeicao >= (now() AT TIME ZONE 'UTC') - interval '{intervalo}'
                 GROUP BY 1
            ),
            buckets AS (
                SELECT bucket FROM aceitas
                UNION
                SELECT bucket FROM rejeitadas
            )
            SELECT b.bucket AS instante,
                   COALESCE(a.gravadas, 0) AS gravadas,
                   COALESCE(r.rejeitadas, 0) AS rejeitadas
              FROM buckets b
              LEFT JOIN aceitas a ON a.bucket = b.bucket
              LEFT JOIN rejeitadas r ON r.bucket = b.bucket
             ORDER BY b.bucket ASC
            """
        )
        rows = cur.fetchall()

    pontos = []
    for row in rows:
        g = row["gravadas"]
        rj = row["rejeitadas"]
        tot = g + rj
        pontos.append({
            "instante": row["instante"].isoformat() + "Z" if row["instante"] else None,
            "gravadas": g,
            "rejeitadas": rj,
            "pdr_pct": round(g / tot * 100, 1) if tot > 0 else 100.0,
        })

    return {"periodo": periodo, "pontos": pontos}


@router.post("/ingestao/sincronizar", dependencies=permissao_analista)
def sincronizar_ingestao_thingspeak():
    """Executa coleta sob demanda da última leitura no ThingSpeak e registra no banco."""
    try:
        leitura = thingspeak_client.buscar_ultima_leitura()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar ThingSpeak: {exc}")

    if leitura is None:
        return {"resultado": "sem_leitura_nova", "detalhe": "Canal ThingSpeak sem leituras disponíveis."}

    resultado = database.processar_leitura(leitura)
    return {
        "resultado": resultado,
        "entry_id": leitura.get("entry_id"),
        "temperatura": leitura.get("temperatura"),
        "umidade": leitura.get("umidade"),
    }
