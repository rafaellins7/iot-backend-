# Termos: https://open-meteo.com/en/features#terms (citar a Open-Meteo na interface).
from datetime import datetime
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
        return {"descricao": "Disponível", "condicao": "Disponível", "icone": "sol"}
    for ini, fim, descricao, icone in _CODIGOS_WMO:
        if ini <= codigo <= fim:
            return {"descricao": descricao, "condicao": descricao, "icone": icone}
    return {"descricao": "Céu limpo", "condicao": "Céu limpo", "icone": "sol"}


def buscar_previsao(latitude: float, longitude: float, timezone: str, dias: int = 7) -> dict:
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
    desc = descrever_codigo(atual.get("weather_code"))
    return {**atual, "uv_index": uv, **desc}


def normalizar(bruto: dict) -> dict:
    bloco_agora = _bloco_agora(bruto) or {}
    horas = _colunas_para_linhas(bruto.get("hourly", {}))
    dias_brutos = _colunas_para_linhas(bruto.get("daily", {}))

    # Identificar temperaturas por período do dia atual (Manhã ~ 09h, Tarde ~ 15h, Noite ~ 21h)
    data_atual_str = (bloco_agora.get("time") or "")[:10]
    manha_temp = None
    tarde_temp = None
    noite_temp = None

    for h in horas:
        t = h.get("time") or ""
        if t.startswith(data_atual_str):
            if "T09:" in t or " 09:" in t:
                manha_temp = h.get("temperature_2m")
            elif "T15:" in t or " 15:" in t:
                tarde_temp = h.get("temperature_2m")
            elif "T21:" in t or " 21:" in t:
                noite_temp = h.get("temperature_2m")

    dias_semana_pt = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    dias_formatados = []

    for idx, d in enumerate(dias_brutos):
        data_str = d.get("time") or ""
        nome_dia = ""
        try:
            dt = datetime.strptime(data_str[:10], "%Y-%m-%d")
            nome_dia = "Hoje" if idx == 0 else dias_semana_pt[dt.weekday()]
        except Exception:
            nome_dia = data_str

        t_max = d.get("temperature_2m_max")
        t_min = d.get("temperature_2m_min")
        desc = descrever_codigo(d.get("weather_code"))

        dia_item = {
            **d,
            **desc,
            "data": data_str,
            "dia_semana": nome_dia,
            "temp_max": round(t_max, 1) if t_max is not None else None,
            "temp_min": round(t_min, 1) if t_min is not None else None,
            "chuva_mm": d.get("precipitation_sum"),
            "probabilidade_chuva": d.get("precipitation_probability_max"),
            "uv_max": d.get("uv_index_max"),
        }
        dias_formatados.append(dia_item)

    temp_atual = bloco_agora.get("temperature_2m")
    umid_atual = bloco_agora.get("relative_humidity_2m")
    vento_atual = bloco_agora.get("wind_speed_10m")
    sensacao_atual = bloco_agora.get("apparent_temperature")
    chuva_atual = bloco_agora.get("precipitation")
    uv_atual = bloco_agora.get("uv_index")

    if manha_temp is None and dias_formatados:
        manha_temp = dias_formatados[0].get("temp_min")
    if tarde_temp is None and dias_formatados:
        tarde_temp = dias_formatados[0].get("temp_max")
    if noite_temp is None and temp_atual is not None:
        noite_temp = round(temp_atual, 1)

    periodos_dia = {
        "manha": round(manha_temp, 1) if manha_temp is not None else None,
        "tarde": round(tarde_temp, 1) if tarde_temp is not None else None,
        "noite": round(noite_temp, 1) if noite_temp is not None else None,
    }

    agora_enriquecido = {
        **bloco_agora,
        "temperatura": round(temp_atual, 1) if temp_atual is not None else None,
        "umidade": round(umid_atual, 1) if umid_atual is not None else None,
        "vento_kmh": round(vento_atual, 1) if vento_atual is not None else None,
        "sensacao_termica": round(sensacao_atual, 1) if sensacao_atual is not None else None,
        "chuva_mm": chuva_atual if chuva_atual is not None else 0.0,
        "uv": uv_atual,
        "condicao": bloco_agora.get("descricao") or "Predomínio de sol",
        "cidade": "Petrolina, PE",
    }

    return {
        "fonte": "Open-Meteo",
        "origem": "previsao",
        "latitude": bruto.get("latitude"),
        "longitude": bruto.get("longitude"),
        "timezone": bruto.get("timezone"),
        "cidade": "Petrolina, PE",
        "agora": agora_enriquecido,
        "atual": agora_enriquecido,
        # Atalhos diretos de primeiro nível para compatibilidade universal
        "temperatura": agora_enriquecido.get("temperatura"),
        "temperatura_atual": agora_enriquecido.get("temperatura"),
        "umidade": agora_enriquecido.get("umidade"),
        "umidade_atual": agora_enriquecido.get("umidade"),
        "vento_kmh": agora_enriquecido.get("vento_kmh"),
        "sensacao_termica": agora_enriquecido.get("sensacao_termica"),
        "chuva_mm": agora_enriquecido.get("chuva_mm"),
        "uv": agora_enriquecido.get("uv"),
        "descricao": agora_enriquecido.get("descricao"),
        "condicao": agora_enriquecido.get("condicao"),
        "icone": agora_enriquecido.get("icone"),
        "periodos_dia": periodos_dia,
        "unidades_agora": bruto.get("current_units", {}),
        "unidades_hora": bruto.get("hourly_units", {}),
        "unidades_dia": bruto.get("daily_units", {}),
        "horas": horas,
        "dias": dias_formatados,
    }
