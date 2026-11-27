from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from src.api.deps import get_conn
from src.api.deps_auth import get_current_user
from src.api.escopo import id_dono

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

STATUS_ALERTA_ABERTO = "aberto"

ORDEM_ETAPAS = ["Em produção", "Pronto para colheita", "Colhido",
                "Em transporte", "Armazenado", "Finalizado"]


def _arred(valor, casas):
    return None if valor is None else round(float(valor), casas)


def _condicao_geral(selos: dict) -> dict:
    """Pior selo entre os lotes avaliados pela vw_lote_saude."""
    criticos = selos.get("Crítico", 0)
    atencao = selos.get("Atenção", 0)
    saudaveis = selos.get("Saudável", 0)
    avaliados = criticos + atencao + saudaveis
    if avaliados == 0:
        nivel, rotulo = None, None
    elif criticos:
        nivel, rotulo = "critica", "Crítica"
    elif atencao:
        nivel, rotulo = "atencao", "Atenção"
    else:
        nivel, rotulo = "boa", "Boa"
    return {
        "nivel": nivel,
        "rotulo": rotulo,
        "lotes_avaliados": avaliados,
        "lotes_criticos": criticos,
        "lotes_atencao": atencao,
        "lotes_saudaveis": saudaveis,
    }


@router.get("/resumo")
def resumo(conn=Depends(get_conn), user=Depends(get_current_user)):
    # Produtor: todos os números abaixo consideram só os sensores/lotes dele (None = escopo total)
    p = {"dono": id_dono(user)}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Cartão "Sensores ativos": real = tem leitura com origem 'thingspeak' ou 'thingspeak-solo'
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE s.status::text = 'ativo')::int AS ativos,
                   COUNT(*)::int AS total,
                   COUNT(*) FILTER (
                       WHERE s.status::text = 'ativo'
                         AND EXISTS (SELECT 1 FROM leitura_climatica l
                                     WHERE l.fk_sensor_id_sensor = s.id_sensor
                                       AND lower(l.origem) LIKE 'thingspeak%%')
                   )::int AS reais
            FROM sensor s
            WHERE (%(dono)s::int IS NULL OR s.fk_usuario_id_usuario = %(dono)s)
        """, p)
        sensores = cur.fetchone()

        # Cartão "Lotes monitorados": só lotes não finalizados
        cur.execute("""
            SELECT COUNT(*)::int AS total,
                   COUNT(*) FILTER (
                       WHERE EXISTS (SELECT 1 FROM sensor s
                                     WHERE s.fk_lote_id_lote = l.id_lote
                                       AND s.status::text = 'ativo')
                   )::int AS com_sensor_ativo
            FROM lote l
            WHERE l.status::text <> 'Finalizado'
              AND (%(dono)s::int IS NULL OR l.fk_usuario_id_usuario = %(dono)s)
        """, p)
        lotes = cur.fetchone()

        # Cartão "Alertas ativos"
        cur.execute("""
            SELECT COUNT(*)::int AS abertos,
                   COUNT(*) FILTER (WHERE a.fk_leitura_id_leitura IS NOT NULL)::int AS reativos,
                   COUNT(*) FILTER (WHERE a.fk_leitura_id_leitura IS NULL
                                      AND a.fk_previsao_id_previsao IS NOT NULL)::int AS preditivos,
                   MAX(a.nivel)::text AS maior_nivel
            FROM alerta a
            LEFT JOIN leitura_climatica r ON r.id_leitura = a.fk_leitura_id_leitura
            LEFT JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
            WHERE lower(a.status) = lower(%(status)s)
              AND (%(dono)s::int IS NULL OR s.fk_usuario_id_usuario = %(dono)s)
        """, {**p, "status": STATUS_ALERTA_ABERTO})
        alertas = cur.fetchone()

        # "Fluxo operacional dos lotes"
        cur.execute("""
            SELECT l.status::text AS status, COUNT(*)::int AS qtd
            FROM lote l
            WHERE (%(dono)s::int IS NULL OR l.fk_usuario_id_usuario = %(dono)s)
            GROUP BY 1
        """, p)
        por_status = {r["status"]: r["qtd"] for r in cur.fetchall()}

        # Cartão "Condição geral": selos da vw_lote_saude (só ar, últimas 24 h)
        cur.execute("""
            SELECT v.selo AS selo, COUNT(*)::int AS qtd
            FROM vw_lote_saude v
            JOIN lote l ON l.id_lote = v.id_lote
            WHERE l.status::text <> 'Finalizado'
              AND (%(dono)s::int IS NULL OR l.fk_usuario_id_usuario = %(dono)s)
            GROUP BY v.selo
        """, p)
        selos = {r["selo"]: r["qtd"] for r in cur.fetchall()}

        # Cartão "Resumo das condições": % dentro da faixa (media ponderada dos lotes)
        cur.execute("""
            SELECT COALESCE(SUM(v.n_leituras), 0)::int AS n,
                   SUM(v.pct_na_faixa * v.n_leituras) / NULLIF(SUM(v.n_leituras), 0) AS pct
            FROM vw_lote_saude v
            JOIN lote l ON l.id_lote = v.id_lote
            WHERE l.status::text <> 'Finalizado'
              AND (%(dono)s::int IS NULL OR l.fk_usuario_id_usuario = %(dono)s)
        """, p)
        faixa = cur.fetchone()

        # ... medias do ar nas ultimas 24 h e VPD (Tetens, FAO-56) leitura a leitura
        cur.execute("""
            SELECT COUNT(*)::int AS n,
                   AVG(r.temperatura::float8) AS temp_media,
                   AVG(r.umidade::float8) AS umid_media,
                   AVG(0.6108 * exp(17.27 * r.temperatura::float8
                                    / (r.temperatura::float8 + 237.3))
                       * (1 - r.umidade::float8 / 100.0)) AS vpd_medio
            FROM leitura_climatica r
            JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
            WHERE s.ambiente = 'ar'
              AND lower(r.origem) = 'thingspeak'
              AND r.data_hora >= (now() AT TIME ZONE 'UTC') - interval '24 hours'
              AND (%(dono)s::int IS NULL OR s.fk_usuario_id_usuario = %(dono)s)
        """, p)
        ar = cur.fetchone()

        # Media de umidade do solo nas ultimas 24 h (sensores reais de solo)
        cur.execute("""
            SELECT COUNT(*)::int AS n,
                   AVG(COALESCE(r.umidade_solo, r.umidade)::float8) AS solo_media
            FROM leitura_climatica r
            JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
            WHERE s.ambiente = 'solo'
              AND lower(r.origem) LIKE 'thingspeak%%'
              AND r.data_hora >= (now() AT TIME ZONE 'UTC') - interval '24 hours'
              AND (%(dono)s::int IS NULL OR s.fk_usuario_id_usuario = %(dono)s)
        """, p)
        solo = cur.fetchone()

    total_monit = lotes["total"]
    return {
        "lotes_monitorados": {
            "com_sensor_ativo": lotes["com_sensor_ativo"],
            "total": total_monit,
            "percentual": round(100 * lotes["com_sensor_ativo"] / total_monit) if total_monit else None,
        },
        "sensores": {
            "ativos": sensores["ativos"],
            "total": sensores["total"],
            "reais": sensores["reais"],
            "simulados": sensores["ativos"] - sensores["reais"],
        },
        "alertas": alertas,
        "condicao_geral": _condicao_geral(selos),
        "resumo_condicoes": {
            "janela_horas": 24,
            "pct_na_faixa": _arred(faixa["pct"], 1),       # null = sem faixa / sem leitura
            "leituras_avaliadas": faixa["n"],
            "n_leituras_ar": ar["n"],
            "n_leituras_solo": solo["n"],
            "temperatura_ar_media": _arred(ar["temp_media"], 1),
            "umidade_ar_media": _arred(ar["umid_media"], 0),
            "umidade_solo_media": _arred(solo["solo_media"], 1),
            "vpd_medio_kpa": _arred(ar["vpd_medio"], 2),
        },
        "fluxo_lotes": {
            "total_cadastrados": sum(por_status.values()),
            "etapas": [{"status": s, "qtd": por_status.get(s, 0)} for s in ORDEM_ETAPAS],
        },
    }