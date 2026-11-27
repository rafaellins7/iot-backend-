# Termos: https://open-meteo.com/en/features#terms (citar a Open-Meteo na interface).
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone

import requests

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

BASE_URL = "https://api.open-meteo.com/v1/forecast"
MET_NORWAY_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
_HEADERS = {"User-Agent": "RaizAgroIoT/1.0 (+https://raiz-agro-iot.vercel.app)"}

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
    ultimo_erro = None
    for tentativa in range(2):
        try:
            resp = requests.get(BASE_URL, params=params, headers=_HEADERS, timeout=10)
            if resp.status_code == 429:
                resp.raise_for_status()
            if resp.status_code >= 500 and tentativa == 0:
                time.sleep(1.5)
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.Timeout, requests.ConnectionError) as e:
            ultimo_erro = e
            if tentativa == 0:
                time.sleep(1.5)
                continue
            raise
    if ultimo_erro:
        raise ultimo_erro
    raise requests.RequestException("Falha ao consultar Open-Meteo")


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


def _resolver_tz(tz_nome: str):
    if ZoneInfo is not None and tz_nome:
        try:
            return ZoneInfo(tz_nome)
        except Exception:
            pass
    # Fallback seguro para America/Recife (UTC-3) se tzdata não estiver instalado
    return dt_timezone(timedelta(hours=-3))


def _symbol_para_wmo(symbol_code: str | None) -> int | None:
    if not symbol_code:
        return None
    base = symbol_code.split("_")[0].lower()
    if "thunder" in base:
        return 95
    if base == "clearsky":
        return 0
    if base == "fair":
        return 1
    if base == "partlycloudy":
        return 2
    if base == "cloudy":
        return 3
    if base == "fog":
        return 45
    if "snow" in base:
        return 71
    if "showers" in base:
        return 80
    if base in ("lightrain", "drizzle"):
        return 51
    if "rain" in base or "sleet" in base:
        return 61
    return 2


def _calcular_vpd(temp_c: float | None, rh_pct: float | None) -> float | None:
    if temp_c is None or rh_pct is None:
        return None
    es = 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
    return round(max(0.0, es * (1.0 - (rh_pct / 100.0))), 2)


def buscar_previsao_met_norway(latitude: float, longitude: float) -> dict:
    """Provedor meteorológico secundário oficial (MET Norway, gratuito, sem API key)."""
    resp = requests.get(
        MET_NORWAY_URL,
        params={"lat": round(latitude, 4), "lon": round(longitude, 4)},
        headers=_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def normalizar_met_norway(bruto: dict, latitude: float, longitude: float, tz_nome: str, dias: int = 3) -> dict:
    tz = _resolver_tz(tz_nome)
    series = bruto.get("properties", {}).get("timeseries") or []
    horas = []
    por_dia = defaultdict(lambda: {"temps": [], "chuva": 0.0, "tem_chuva": False, "codes": []})

    agora_bloco = None
    for idx, item in enumerate(series):
        ts_raw = item.get("time")
        if not ts_raw:
            continue
        dt_utc = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(tz)
        data_str = dt_local.strftime("%Y-%m-%d")
        hora_str = dt_local.strftime("%Y-%m-%dT%H:%M")

        dados = item.get("data") or {}
        inst = (dados.get("instant") or {}).get("details") or {}
        temp = inst.get("air_temperature")
        umid = inst.get("relative_humidity")
        vento_ms = inst.get("wind_speed")
        vento_kmh = round(vento_ms * 3.6, 1) if vento_ms is not None else None

        n1 = dados.get("next_1_hours") or {}
        n6 = dados.get("next_6_hours") or {}
        n12 = dados.get("next_12_hours") or {}

        sym = (
            (n1.get("summary") or {}).get("symbol_code")
            or (n6.get("summary") or {}).get("symbol_code")
            or (n12.get("summary") or {}).get("symbol_code")
        )
        wmo = _symbol_para_wmo(sym)

        chuva_1h = (n1.get("details") or {}).get("precipitation_amount")
        chuva_6h = (n6.get("details") or {}).get("precipitation_amount")

        if idx == 0:
            agora_bloco = {
                "time": hora_str,
                "temperature_2m": temp,
                "relative_humidity_2m": umid,
                "apparent_temperature": temp,
                "precipitation": chuva_1h if chuva_1h is not None else (chuva_6h if chuva_6h is not None else 0.0),
                "weather_code": wmo,
                "wind_speed_10m": vento_kmh,
                "uv_index": None,
                **descrever_codigo(wmo),
            }

        horas.append({
            "time": hora_str,
            "temperature_2m": temp,
            "relative_humidity_2m": umid,
            "precipitation_probability": None,
            "precipitation": chuva_1h if chuva_1h is not None else 0.0,
            "vapour_pressure_deficit": _calcular_vpd(temp, umid),
            "et0_fao_evapotranspiration": None,
            "uv_index": None,
        })

        bucket = por_dia[data_str]
        if temp is not None:
            bucket["temps"].append(temp)
        if chuva_1h is not None:
            bucket["chuva"] += float(chuva_1h)
            bucket["tem_chuva"] = True
        elif chuva_6h is not None and dt_local.hour in (0, 6, 12, 18):
            bucket["chuva"] += float(chuva_6h)
            bucket["tem_chuva"] = True
        if wmo is not None:
            bucket["codes"].append(wmo)

    dias_lista = []
    for data_str in sorted(por_dia.keys())[:dias]:
        b = por_dia[data_str]
        wmo_dia = Counter(b["codes"]).most_common(1)[0][0] if b["codes"] else None
        dias_lista.append({
            "time": data_str,
            "weather_code": wmo_dia,
            "temperature_2m_max": round(max(b["temps"]), 1) if b["temps"] else None,
            "temperature_2m_min": round(min(b["temps"]), 1) if b["temps"] else None,
            "precipitation_sum": round(b["chuva"], 2) if b["tem_chuva"] else 0.0,
            "precipitation_probability_max": None,
            "uv_index_max": None,
            "et0_fao_evapotranspiration": None,
            **descrever_codigo(wmo_dia),
        })

    datas_validas = {d["time"] for d in dias_lista}
    horas_filtradas = [h for h in horas if h["time"][:10] in datas_validas]

    return {
        "fonte": "MET Norway",
        "origem": "previsao",
        "latitude": latitude,
        "longitude": longitude,
        "timezone": tz_nome,
        "agora": agora_bloco,
        "unidades_agora": {
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "wind_speed_10m": "km/h",
            "precipitation": "mm",
        },
        "unidades_hora": {
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "precipitation": "mm",
            "vapour_pressure_deficit": "kPa",
        },
        "unidades_dia": {
            "temperature_2m_max": "°C",
            "temperature_2m_min": "°C",
            "precipitation_sum": "mm",
        },
        "horas": horas_filtradas,
        "dias": dias_lista,
    }