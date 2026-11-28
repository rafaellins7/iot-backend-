"""Resumos agregados para as telas do perfil Analista. Só dados reais (origem 'thingspeak')."""
from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from src import config
from src.api.deps import get_conn

router = APIRouter(prefix="/analista", tags=["analista"])

AGORA_UTC = "(now() AT TIME ZONE 'UTC')"


@router.get("/sensores/resumo")
def resumo_sensores(conn=Depends(get_conn)):
    """Cartões das telas Sensores e Rede: contagem por ambiente, ingestão e rejeição (UTC)."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE status::text = 'ativo')::int AS ativos,
                   COUNT(*) FILTER (WHERE status::text <> 'ativo')::int AS inativos,
                   COUNT(*) FILTER (WHERE ambiente = 'solo')::int AS total_solo,
                   COUNT(*) FILTER (WHERE ambiente = 'ar')::int AS total_ar,
                   COUNT(*) FILTER (WHERE status::text = 'ativo' AND ambiente = 'solo')::int AS ativos_solo,
                   COUNT(*) FILTER (WHERE status::text = 'ativo' AND ambiente = 'ar')::int AS ativos_ar
              FROM sensor
            """
        )
        sensores = cur.fetchone()

        cur.execute(
            f"""
            SELECT COUNT(*)::int AS gravadas, MAX(data_hora) AS ultima_leitura
              FROM leitura_climatica
             WHERE lower(origem) = 'thingspeak'
               AND data_hora >= {AGORA_UTC} - interval '24 hours'
            """
        )
        ing = cur.fetchone()

        cur.execute(
            f"""
            SELECT COUNT(*) FILTER (WHERE data_rejeicao >= {AGORA_UTC} - interval '24 hours')::int AS rejeitadas_24h,
                   COUNT(*) FILTER (WHERE data_rejeicao >= date_trunc('day', {AGORA_UTC}))::int AS rejeitadas_hoje
              FROM leitura_rejeitada
             WHERE lower(origem) = 'thingspeak'
            """
        )
        rej = cur.fetchone()

        cur.execute("SELECT COUNT(*)::int AS n FROM alerta WHERE lower(status) = 'aberto'")
        reativos = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*)::int AS n FROM alertas_preditivos WHERE upper(status) = 'EM ABERTO'")
        preditivos = cur.fetchone()["n"]

    recebidas = ing["gravadas"] + rej["rejeitadas_24h"]
    ultima = ing["ultima_leitura"]
    return {
        "sensores": sensores,
        "coleta": {
            "intervalo_s": config.POLL_INTERVAL_SECONDS,
            "fonte": "ThingSpeak",
            "canal": config.THINGSPEAK_CHANNEL_ID,
        },
        "ingestao_24h": {
            "gravadas": ing["gravadas"],
            "rejeitadas": rej["rejeitadas_24h"],
            "taxa_sucesso_pct": round(ing["gravadas"] / recebidas * 100, 1) if recebidas else None,
            "ultima_leitura": ultima.isoformat() + "Z" if ultima else None,
        },
        "rejeitadas_hoje": rej["rejeitadas_hoje"],
        "alertas_abertos": {"reativos": reativos, "preditivos": preditivos, "total": reativos + preditivos},
    }


@router.get("/alertas/resumo")
def resumo_alertas(conn=Depends(get_conn)):
    """Distribuição de incidentes abertos por severidade, com a fração de perda de cada nível."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT 'BAIXO' AS nivel, 'baixo' AS categoria,
                   COUNT(*) FILTER (WHERE upper(a.status) = 'EM ABERTO' AND upper(a.nivel_severidade) = 'BAIXO')::int AS abertos
              FROM alertas_preditivos a
            UNION ALL
            SELECT 'MEDIO', 'médio',
                   COUNT(*) FILTER (WHERE upper(a.status) = 'EM ABERTO' AND upper(a.nivel_severidade) = 'MEDIO')::int
              FROM alertas_preditivos a
            UNION ALL
            SELECT 'CRITICO', 'alto',
                   COUNT(*) FILTER (WHERE upper(a.status) = 'EM ABERTO' AND upper(a.nivel_severidade) = 'CRITICO')::int
              FROM alertas_preditivos a
            """
        )
        niveis = cur.fetchall()
        cur.execute("SELECT categoria::text AS categoria, fracao_perda FROM perda_risco")
        perdas = {r["categoria"]: float(r["fracao_perda"]) for r in cur.fetchall()}

    total = sum(n["abertos"] for n in niveis)
    return {
        "total_abertos": total,
        "distribuicao": [
            {
                "nivel": n["nivel"],
                "abertos": n["abertos"],
                "percentual": round(n["abertos"] / total * 100, 1) if total else None,
                "fracao_perda": perdas.get(n["categoria"]),
            }
            for n in niveis
        ],
    }


@router.get("/rede/historico")
def historico_rede_pdr(horas: int = 24, conn=Depends(get_conn)):
    """Série horária real de PDR (Packet Delivery Ratio) nas últimas N horas."""
    horas = max(1, min(72, int(horas)))
    intervalo_s = max(1, int(getattr(config, "ESP32_INTERVALO_ENVIO_S", None) or config.POLL_INTERVAL_SECONDS or 20))
    esperadas_hora = max(1, int(3600 / intervalo_s))

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            WITH horas_ar AS (
                SELECT date_trunc('hour', data_hora) AS hora_utc,
                       COUNT(*)::int AS gravadas
                  FROM leitura_climatica
                 WHERE lower(COALESCE(origem, '')) LIKE 'thingspeak%%'
                   AND data_hora >= date_trunc('hour', {AGORA_UTC}) - make_interval(hours => %s)
                 GROUP BY 1
            ),
            horas_rej AS (
                SELECT date_trunc('hour', data_rejeicao) AS hora_utc,
                       COUNT(*)::int AS rejeitadas
                  FROM leitura_rejeitada
                 WHERE lower(COALESCE(origem, '')) LIKE 'thingspeak%%'
                   AND data_rejeicao >= date_trunc('hour', {AGORA_UTC}) - make_interval(hours => %s)
                 GROUP BY 1
            )
            SELECT COALESCE(a.hora_utc, r.hora_utc) AS hora_utc,
                   COALESCE(a.gravadas, 0)::int AS gravadas,
                   COALESCE(r.rejeitadas, 0)::int AS rejeitadas,
                   EXTRACT(EPOCH FROM ({AGORA_UTC} - COALESCE(a.hora_utc, r.hora_utc)))::float AS seg_decorridos
              FROM horas_ar a
              FULL OUTER JOIN horas_rej r ON r.hora_utc = a.hora_utc
             ORDER BY 1 ASC
            """,
            (horas, horas),
        )
        rows = cur.fetchall()

    pontos = []
    for r in rows:
        grav = int(r["gravadas"])
        rej = int(r["rejeitadas"])
        seg = max(float(intervalo_s), min(3600.0, float(r["seg_decorridos"] or 3600.0)))
        esp = max(1, int(seg / intervalo_s))
        total_rec = grav + rej
        denom = max(esp, total_rec)
        pdr = round(min(100.0, (grav / denom) * 100.0), 1) if denom > 0 else 0.0
        dt = r["hora_utc"]
        instante_iso = dt.isoformat() + "Z" if dt else None
        pontos.append({
            "instante": instante_iso,
            "hora": instante_iso,
            "gravadas": grav,
            "rejeitadas": rej,
            "esperadas": esp,
            "pdr_pct": pdr,
            "rssi_dbm": None,
        })

    return {
        "horas": horas,
        "intervalo_s": intervalo_s,
        "esperadas_por_hora": esperadas_hora,
        "pontos": pontos,
    }
