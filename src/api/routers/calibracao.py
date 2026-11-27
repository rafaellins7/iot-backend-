from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from src import config
from src.api.deps import get_conn
from src.api.deps_auth import ADMIN, ANALISTA, require_role

# Cria o router com prefixo /calibracao
router = APIRouter(prefix="/calibracao", tags=["calibracao"])

# Garante que apenas Analista e Administrador possam acessar/calibrar
auth_analista = [Depends(require_role(ANALISTA, ADMIN))]


def _f(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


# --- SCHEMAS (Entrada/Saída) ---
class CorteRiscoUpdate(BaseModel):
    nivel: str               # "BAIXO", "MEDIO", "CRITICO"
    limiar_min: float        # ex: 0.00, 0.45, 0.75
    limiar_max: float        # ex: 0.45, 0.75, 1.00
    acao_recomendada: str


class LimiarCulturaUpdate(BaseModel):
    temp_min: float
    temp_max: float
    umidade_min: float
    umidade_max: float


class SensorCalibracaoUpdate(BaseModel):
    nome: Optional[str] = None
    localizacao: Optional[str] = None
    status: Optional[str] = None
    fk_lote_id_lote: Optional[int] = None


# --- ENDPOINTS ---

# 1. GET /calibracao/resumo (Entrega tudo que a tela de Calibração precisa num só request)
@router.get("/resumo", dependencies=auth_analista)
def obter_dados_calibracao(conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Busca modelos registrados
        cur.execute("SELECT id_modelo, nome, tipo_modelo, versao, status FROM ia_modelo ORDER BY id_modelo")
        modelos = [dict(r) for r in cur.fetchall()]

        # Busca limiares de culturas com nome real da fruta
        cur.execute("""
            SELECT c.id_config, c.fk_fruta_id_fruta AS id_fruta, f.nome AS fruta,
                   c.etapa, c.temp_min, c.temp_max, c.umidade_min, c.umidade_max
            FROM config_parametro c
            LEFT JOIN fruta f ON f.id_fruta = c.fk_fruta_id_fruta
            ORDER BY c.id_config
        """)
        limiares = [
            {k: _f(v) for k, v in dict(r).items()}
            for r in cur.fetchall()
        ]

        # Busca cortes preditivos
        cur.execute("""
            SELECT nivel, limiar_min, limiar_max, acao_recomendada
            FROM cortes_alerta_preditivo
            ORDER BY limiar_min
        """)
        cortes = [
            {k: _f(v) for k, v in dict(r).items()}
            for r in cur.fetchall()
        ]

        # Busca sensores reais e vínculo com lote/fruta
        cur.execute("""
            SELECT s.id_sensor, s.nome, s.tipo_sensor, s.localizacao,
                   s.ambiente, s.status::text AS status,
                   s.fk_lote_id_lote AS id_lote,
                   CASE WHEN s.fk_lote_id_lote IS NOT NULL THEN 'Lote #' || s.fk_lote_id_lote ELSE NULL END AS lote_codigo,
                   f.nome AS variedade
            FROM sensor s
            LEFT JOIN lote l ON l.id_lote = s.fk_lote_id_lote
            LEFT JOIN fruta f ON f.id_fruta = l.fk_fruta_id_fruta
            ORDER BY s.id_sensor
        """)
        sensores = [dict(r) for r in cur.fetchall()]

        # Contagem real de leituras rejeitadas nas últimas 24h
        cur.execute("""
            SELECT COUNT(*)::int AS total
            FROM leitura_rejeitada
            WHERE data_rejeicao >= (now() AT TIME ZONE 'UTC') - interval '24 hours'
        """)
        rejeitadas_24h = (cur.fetchone() or {}).get("total", 0)

        # Última leitura climática real registrada
        cur.execute("""
            SELECT id_leitura, fk_sensor_id_sensor AS id_sensor, entry_id_thingspeak,
                   data_hora, temperatura, umidade, origem
            FROM leitura_climatica
            ORDER BY data_hora DESC, id_leitura DESC
            LIMIT 1
        """)
        ult = cur.fetchone()
        ultima_leitura = None
        if ult:
            ultima_leitura = {
                "id_leitura": ult["id_leitura"],
                "id_sensor": ult["id_sensor"],
                "entry_id_thingspeak": ult["entry_id_thingspeak"],
                "data_hora": ult["data_hora"].isoformat() + "Z" if ult["data_hora"] else None,
                "temperatura": _f(ult["temperatura"]),
                "umidade": _f(ult["umidade"]),
                "origem": ult["origem"],
            }

        # Lotes ativos disponíveis para vínculo
        cur.execute("""
            SELECT l.id_lote, ('Lote #' || l.id_lote || COALESCE(' — ' || f.nome, '')) AS codigo
            FROM lote l
            LEFT JOIN fruta f ON f.id_fruta = l.fk_fruta_id_fruta
            WHERE l.status IS NULL OR lower(l.status::text) <> 'finalizado'
            ORDER BY l.id_lote DESC
            LIMIT 50
        """)
        lotes_disponiveis = [dict(r) for r in cur.fetchall()]

    return {
        "modelos": modelos,
        "limiares": limiares,
        "cortes": cortes,
        "sensores": sensores,
        "rejeitadas_24h": rejeitadas_24h,
        "broker": {
            "channel_id": config.THINGSPEAK_CHANNEL_ID or None,
            "poll_interval_seconds": config.POLL_INTERVAL_SECONDS,
        },
        "ultima_leitura": ultima_leitura,
        "lotes_disponiveis": lotes_disponiveis,
    }


# 2. PUT /calibracao/cortes (Analista afina a sensibilidade dos alertas preditivos)
@router.put("/cortes", dependencies=auth_analista)
def atualizar_cortes_preditivos(cortes: List[CorteRiscoUpdate], conn=Depends(get_conn)):
    with conn.cursor() as cur:
        for c in cortes:
            cur.execute("""
                UPDATE cortes_alerta_preditivo
                   SET limiar_min = %s, limiar_max = %s, acao_recomendada = %s
                 WHERE nivel = %s
            """, (c.limiar_min, c.limiar_max, c.acao_recomendada, c.nivel))
    conn.commit()
    return {"mensagem": "Cortes preditivos recalibrados com sucesso"}


# 3. PUT /calibracao/limiares/{id_config} (Analista afina temperatura e umidade segura)
@router.put("/limiares/{id_config}", dependencies=auth_analista)
def atualizar_limiar_cultura(id_config: int, dados: LimiarCulturaUpdate, conn=Depends(get_conn)):
    if dados.temp_min >= dados.temp_max:
        raise HTTPException(status_code=400, detail="temp_min deve ser menor que temp_max")
    if dados.umidade_min >= dados.umidade_max:
        raise HTTPException(status_code=400, detail="umidade_min deve ser menor que umidade_max")
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE config_parametro
               SET temp_min = %s, temp_max = %s, umidade_min = %s, umidade_max = %s
             WHERE id_config = %s
        """, (dados.temp_min, dados.temp_max, dados.umidade_min, dados.umidade_max, id_config))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Configuração de limiar não encontrada")
    conn.commit()
    return {"mensagem": "Limiar agronômico atualizado com sucesso"}


# 4. PUT /calibracao/sensores/{id_sensor} (Atualiza nome/localização/status/lote na tabela sensor)
@router.put("/sensores/{id_sensor}", dependencies=auth_analista)
def atualizar_sensor_calibracao(id_sensor: int, dados: SensorCalibracaoUpdate, conn=Depends(get_conn)):
    campos = dados.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(status_code=400, detail="Nenhum campo informado")
    sets, params = [], []
    for k in ("nome", "localizacao", "status", "fk_lote_id_lote"):
        if k in campos:
            sets.append(f"{k} = %s")
            params.append(campos[k])
    params.append(id_sensor)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE sensor SET {', '.join(sets)} WHERE id_sensor = %s", params)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Sensor não encontrado")
    conn.commit()
    return {"mensagem": "Sensor atualizado com sucesso"}


# 5. POST /calibracao/recalcular (Executa recálculo real de alertas preditivos contra cortes_alerta_preditivo)
@router.post("/recalcular", dependencies=auth_analista)
def recalcular_modelos(conn=Depends(get_conn)):
    from src import agendador
    detalhe_alertas = agendador.gerar_alertas_preditivos(conn)
    return {
        "mensagem": "Alertas preditivos reavaliados com base nos cortes atuais.",
        "detalhes": f"Alertas preditivos: {detalhe_alertas}",
    }
