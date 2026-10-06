import time
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Query

from src import config, open_meteo_client

router = APIRouter(prefix="/clima", tags=["clima"])

# Cache em memória, para não chamar a Open-Meteo a cada tela aberta.
_cache: dict = {}


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

    try:
        bruto = open_meteo_client.buscar_previsao(lat, lon, config.CLIMA_TIMEZONE, dias)
    except requests.RequestException as e:
        if guardado:  # serve o cache vencido em vez de quebrar o dashboard
            return guardado[1]
        raise HTTPException(status_code=502, detail=f"Falha ao consultar a Open-Meteo: {e}")

    dados = open_meteo_client.normalizar(bruto)
    _cache[chave] = (agora, dados)
    return dados