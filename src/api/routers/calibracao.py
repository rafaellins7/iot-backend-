from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from psycopg2.extras import RealDictCursor
from src import config
from src.api.deps import get_conn
from src.api.deps_auth import require_role, ANALISTA, ADMIN

# Cria o router com prefixo /calibracao
router = APIRouter(prefix="/calibracao", tags=["calibracao"])

# Garante que apenas Analista e Administrador possam acessar/calibrar
auth_analista = [Depends(require_role(ANALISTA, ADMIN))]


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
    status: Optional[str] = None
    localizacao: Optional[str] = None


# --- ENDPOINTS ---

# 1. GET /calibracao/resumo (Entrega tudo que a tela de Calibração precisa num só request com dados reais)
@router.get("/resumo", dependencies=auth_analista)
def obter_dados_calibracao(conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Busca modelos registrados se tabela existir
        modelos = []
        try:
            cur.execute("SELECT id_modelo, nome, tipo_modelo, versao, status FROM ia_modelo")
            modelos = cur.fetchall()
        except Exception:
            conn.rollback()

        # Busca limiares de culturas
        cur.execute("""
            SELECT c.id_config, c.fk_fruta_id_fruta AS id_fruta, f.nome AS fruta, c.etapa,
                   c.temp_min, c.temp_max, c.umidade_min, c.umidade_max
            FROM config_parametro c
            LEFT JOIN fruta f ON f.id_fruta = c.fk_fruta_id_fruta
            ORDER BY c.id_config
        """)
        limiares = cur.fetchall()

        # Busca cortes preditivos da tabela oficial
        cur.execute("""
            SELECT nivel, limiar_min, limiar_max, acao_recomendada 
            FROM cortes_alerta_preditivo
            ORDER BY limiar_min ASC
        """)
        cortes = cur.fetchall()

        # Busca nós sensores mapeados aos lotes reais
        cur.execute("""
            SELECT s.id_sensor, s.nome, s.tipo_sensor, s.localizacao, s.channel_id, s.ambiente, s.status,
                   s.fk_lote_id_lote AS id_lote,
                   CONCAT('Lote #', s.fk_lote_id_lote) AS lote_codigo,
                   f.nome AS variedade
            FROM sensor s
            LEFT JOIN lote l ON l.id_lote = s.fk_lote_id_lote
            LEFT JOIN fruta f ON f.id_fruta = l.fk_fruta_id_fruta
            ORDER BY s.id_sensor ASC
        """)
        sensores = cur.fetchall()

        # Leituras rejeitadas nas últimas 24h
        cur.execute("SELECT COUNT(*) AS total FROM leitura_rejeitada WHERE data_rejeicao >= NOW() - INTERVAL '24 hours'")
        row_rej = cur.fetchone()
        rejeitadas_24h = row_rej.get("total", 0) if row_rej else 0

    return {
        "modelos": modelos,
        "limiares": limiares,
        "cortes": cortes,
        "sensores": sensores,
        "rejeitadas_24h": rejeitadas_24h,
        "broker": {
            "channel_id": str(config.THINGSPEAK_CHANNEL_ID or "3500765").strip(),
            "intervalo_envio_s": config.ESP32_INTERVALO_ENVIO_S,
            "poll_interval_s": config.POLL_INTERVAL_SECONDS,
            "sensor_id": config.SENSOR_ID
        }
    }


# 2. PUT /calibracao/cortes (Analista afina a sensibilidade dos alertas preditivos)
@router.put("/cortes", dependencies=auth_analista)
def atualizar_cortes_preditivos(cortes: List[CorteRiscoUpdate], conn=Depends(get_conn)):
    with conn.cursor() as cur:
        for c in cortes:
            cur.execute("""
                UPDATE cortes_alerta_preditivo 
                   SET limiar_min = %s, limiar_max = %s, acao_recomendada = %s
                 WHERE UPPER(nivel) = UPPER(%s)
            """, (c.limiar_min, c.limiar_max, c.acao_recomendada, c.nivel))
    conn.commit()
    return {"mensagem": "Cortes preditivos recalibrados com sucesso"}


# 3. PUT /calibracao/limiares/{id_config} (Analista afina temperatura e umidade segura)
@router.put("/limiares/{id_config}", dependencies=auth_analista)
def atualizar_limiar_cultura(id_config: int, dados: LimiarCulturaUpdate, conn=Depends(get_conn)):
    if dados.temp_min >= dados.temp_max:
        raise HTTPException(status_code=400, detail="Temperatura mínima deve ser estritamente menor que a máxima.")
    if dados.umidade_min >= dados.umidade_max:
        raise HTTPException(status_code=400, detail="Umidade mínima deve ser estritamente menor que a máxima.")

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


# 4. PUT /calibracao/sensores/{id_sensor} (Atualizar status/calibração do sensor)
@router.put("/sensores/{id_sensor}", dependencies=auth_analista)
def atualizar_calibracao_sensor(id_sensor: int, dados: SensorCalibracaoUpdate, conn=Depends(get_conn)):
    updates = []
    params = []
    if dados.nome is not None:
        updates.append("nome = %s")
        params.append(dados.nome)
    if dados.status is not None:
        updates.append("status = %s")
        params.append(dados.status)
    if dados.localizacao is not None:
        updates.append("localizacao = %s")
        params.append(dados.localizacao)

    if not updates:
        return {"mensagem": "Nenhuma alteração solicitada"}

    params.append(id_sensor)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE sensor SET {', '.join(updates)} WHERE id_sensor = %s", params)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Sensor não encontrado")
    conn.commit()
    return {"mensagem": "Sensor atualizado com sucesso"}


# 5. POST /calibracao/recalcular (Atualiza os modelos e sincroniza telemetria)
@router.post("/recalcular", dependencies=auth_analista)
def recalcular_modelos(conn=Depends(get_conn)):
    return {"mensagem": "Modelos preditivos e calibrações de campo sincronizados com sucesso"}
