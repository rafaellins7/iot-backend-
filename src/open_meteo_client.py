# Termos: https://open-meteo.com/en/features#terms (citar a Open-Meteo na interface).
import requests

BASE_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation_probability",
    "precipitation",
    "vapour_pressure_deficit",      # kPa
    "et0_fao_evapotranspiration",   # mm/h
    "uv_index",
]
DAILY = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "uv_index_max",
    "et0_fao_evapotranspiration",
]


def buscar_previsao(latitude: float, longitude: float, timezone: str, dias: int = 3) -> dict:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(HOURLY),
        "daily": ",".join(DAILY),
        "timezone": timezone,
        "forecast_days": dias,
    }
    resp = requests.get(BASE_URL, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _colunas_para_linhas(bloco: dict) -> list:
    """A Open-Meteo devolve colunas ({time:[...], uv_index:[...]}); o front prefere linhas."""
    chaves = list(bloco.keys())
    n = len(bloco.get("time", []))
    return [{k: bloco[k][i] for k in chaves} for i in range(n)]


def normalizar(bruto: dict) -> dict:
    return {
        "fonte": "Open-Meteo",
        "origem": "previsao",
        "latitude": bruto.get("latitude"),
        "longitude": bruto.get("longitude"),
        "timezone": bruto.get("timezone"),
        "unidades_hora": bruto.get("hourly_units", {}),
        "unidades_dia": bruto.get("daily_units", {}),
        "horas": _colunas_para_linhas(bruto.get("hourly", {})),
        "dias": _colunas_para_linhas(bruto.get("daily", {})),
    }