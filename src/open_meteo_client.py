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
CURRENT = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",   # sensacao termica
    "precipitation",          # mm
    "weather_code",
    "wind_speed_10m",
]

# Codigos WMO (weather_code) -> texto em portugues e chave de icone para o front.
# (codigo_inicial, codigo_final, descricao, icone)
_CODIGOS_WMO = [
    (0, 0, "Céu limpo", "sol"),
    (1, 1, "Predomínio de sol", "sol"),
    (2, 2, "Parcialmente nublado", "sol_nuvem"),
    (3, 3, "Nublado", "nublado"),
    (45, 48, "Neblina", "neblina"),
    (51, 57, "Garoa", "chuva"),
    (61, 67, "Chuva", "chuva"),
    (71, 77, "Neve", "neve"),
    (80, 82, "Pancadas de chuva", "chuva"),
    (85, 86, "Pancadas de neve", "neve"),
    (95, 99, "Trovoada", "trovoada"),
]


def descrever_codigo(codigo) -> dict:
    if codigo is None:
        return {"descricao": None, "icone": None}
    for ini, fim, descricao, icone in _CODIGOS_WMO:
        if ini <= codigo <= fim:
            return {"descricao": descricao, "icone": icone}
    return {"descricao": "Indisponível", "icone": "desconhecido"}


def buscar_previsao(latitude: float, longitude: float, timezone: str, dias: int = 3) -> dict:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join(CURRENT),
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


def _bloco_agora(bruto: dict):
    """Condicoes atuais. O UV vem da previsao horaria da hora corrente."""
    atual = bruto.get("current")
    if not atual:
        return None
    hora = (atual.get("time") or "")[:13]  # ex.: 2026-10-08T14
    uv = None
    h = bruto.get("hourly", {})
    for t, v in zip(h.get("time", []), h.get("uv_index", [])):
        if t[:13] == hora:
            uv = v
            break
    return {**atual, "uv_index": uv, **descrever_codigo(atual.get("weather_code"))}


def normalizar(bruto: dict) -> dict:
    dias = [
        {**d, **descrever_codigo(d.get("weather_code"))}
        for d in _colunas_para_linhas(bruto.get("daily", {}))
    ]
    return {
        "fonte": "Open-Meteo",
        "origem": "previsao",
        "latitude": bruto.get("latitude"),
        "longitude": bruto.get("longitude"),
        "timezone": bruto.get("timezone"),
        "agora": _bloco_agora(bruto),
        "unidades_agora": bruto.get("current_units", {}),
        "unidades_hora": bruto.get("hourly_units", {}),
        "unidades_dia": bruto.get("daily_units", {}),
        "horas": _colunas_para_linhas(bruto.get("hourly", {})),
        "dias": dias,
    }