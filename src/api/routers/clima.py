import logging
import time
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Query
from psycopg2.extras import RealDictCursor

from src import config, database, open_meteo_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clima", tags=["clima"])

# Cache em memória, para não chamar a Open-Meteo a cada tela aberta.
_cache: dict = {}
# Cooldown após falha externa (ex.: 429 Too Many Requests) para não martelar a Open-Meteo
_cooldown_ate: dict = {}
_COOLDOWN_ERRO_S = 120.0


def _fallback_sensor_local(lat: float, lon: float, motivo: str) -> dict:
    """Devolve resposta 200 compatível usando a última leitura real do sensor de ar (sem inventar dados)."""
    agora = None
    try:
        with database.conectar() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT l.temperatura, l.umidade, l.data_hora
                    FROM leitura_climatica l
                    JOIN sensor s ON s.id_sensor = l.fk_sensor_id_sensor
                    WHERE s.ambiente = 'ar'
                      AND l.temperatura IS NOT NULL
                    ORDER BY l.data_hora DESC, l.id_leitura DESC
                    LIMIT 1
                """)
                r = cur.fetchone()
                if r:
                    agora = {
                        "time": r["data_hora"].isoformat() + "Z" if r["data_hora"] else None,
                        "temperature_2m": float(r["temperatura"]) if r["temperatura"] is not None else None,
                        "relative_humidity_2m": float(r["umidade"]) if r["umidade"] is not None else None,
                        "precipitation": None,
                        "wind_speed_10m": None,
                        "uv_index": None,
                        "weather_code": None,
                        "descricao": "Leitura do sensor local (previsão externa indisponível)",
                        "icone": None,
                    }
    except Exception as db_err:
        logger.warning("[CLIMA] Fallback de sensor local indisponível: %s", str(db_err)[:120])

    return {
        "fonte": "Sensor Local (Open-Meteo indisponível)" if agora else "Indisponível",
        "origem": "fallback_sensor" if agora else "indisponivel",
        "indisponivel": True,
        "motivo": motivo,
        "latitude": lat,
        "longitude": lon,
        "timezone": config.CLIMA_TIMEZONE,
        "agora": agora,
        "unidades_agora": {"temperature_2m": "°C", "relative_humidity_2m": "%"},
        "unidades_hora": {},
        "unidades_dia": {},
        "horas": [],
        "dias": [],
    }


@router.get("/previsao")
def previsao(
    dias: int = Query(3, ge=1, le=7),
    latitude: Optional[float] = Query(None, ge=-90, le=90),
    longitude: Optional[float] = Query(None, ge=-180, le=180),
):
    lat = latitude if latitude is not None else config.CLIMA_LATITUDE
    lon = longitude if longitude is not None else config.CLIMA_LONGITUDE
    if lat in (None, "") or lon in (None, ""):
        raise HTTPException(
            status_code=503,
            detail="Coordenadas de referência não configuradas (CLIMA_LATITUDE/CLIMA_LONGITUDE no .env)",
        )
    lat, lon = round(float(lat), 3), round(float(lon), 3)

    chave = (lat, lon, dias)
    agora = time.monotonic()
    guardado = _cache.get(chave)
    if guardado and agora - guardado[0] < config.CLIMA_CACHE_SEGUNDOS:
        return guardado[1]

    # Se Open-Meteo falhou recentemente (ex.: 429), tenta MET Norway diretamente durante o cooldown
    ate = _cooldown_ate.get(chave, 0.0)
    if agora < ate:
        if guardado:
            return guardado[1]
        try:
            bruto_met = open_meteo_client.buscar_previsao_met_norway(lat, lon)
            dados_met = open_meteo_client.normalizar_met_norway(bruto_met, lat, lon, config.CLIMA_TIMEZONE, dias)
            _cache[chave] = (agora, dados_met)
            return dados_met
        except requests.RequestException as met_err:
            logger.warning("[CLIMA] MET Norway indisponível durante cooldown: %s", str(met_err)[:140])
            return _fallback_sensor_local(lat, lon, "Open-Meteo em cooldown e MET Norway indisponível")

    try:
        bruto = open_meteo_client.buscar_previsao(lat, lon, config.CLIMA_TIMEZONE, dias)
    except requests.RequestException as e:
        _cooldown_ate[chave] = agora + _COOLDOWN_ERRO_S
        logger.warning("[CLIMA] Open-Meteo indisponível (%s); tentando MET Norway", str(e)[:150])
        try:
            bruto_met = open_meteo_client.buscar_previsao_met_norway(lat, lon)
            dados_met = open_meteo_client.normalizar_met_norway(bruto_met, lat, lon, config.CLIMA_TIMEZONE, dias)
            _cache[chave] = (agora, dados_met)
            return dados_met
        except requests.RequestException as met_err:
            logger.warning("[CLIMA] MET Norway também falhou (%s)", str(met_err)[:140])
        if guardado:  # serve o cache vencido em vez de quebrar o dashboard
            return guardado[1]
        return _fallback_sensor_local(lat, lon, f"Open-Meteo indisponível: {str(e)[:140]}")

    dados = open_meteo_client.normalizar(bruto)
    _cache[chave] = (agora, dados)
    _cooldown_ate.pop(chave, None)
    return dados
