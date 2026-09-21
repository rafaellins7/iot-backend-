# field1 = temperatura, field2 = umidade
import requests
from src import config

BASE_URL = "https://api.thingspeak.com"


def buscar_ultima_leitura():
    url = f"{BASE_URL}/channels/{config.THINGSPEAK_CHANNEL_ID}/feeds/last.json"
    params = {}
    if config.THINGSPEAK_READ_API_KEY:
        params["api_key"] = config.THINGSPEAK_READ_API_KEY

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    dado = resp.json()

    # Canal vazio retorna {} ou campos vazios
    if not dado or dado.get("entry_id") is None:
        return None

    return {
        "entry_id": dado["entry_id"],
        "created_at": dado["created_at"],
        "temperatura": _float_seguro(dado.get("field1")),
        "umidade": _float_seguro(dado.get("field2")),
    }


def buscar_leituras(quantidade=100):
    url = f"{BASE_URL}/channels/{config.THINGSPEAK_CHANNEL_ID}/feeds.json"
    params = {"results": quantidade}
    if config.THINGSPEAK_READ_API_KEY:
        params["api_key"] = config.THINGSPEAK_READ_API_KEY

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    dado = resp.json()

    leituras = []
    for feed in dado.get("feeds", []):
        if feed.get("entry_id") is None:
            continue
        leituras.append({
            "entry_id": feed["entry_id"],
            "created_at": feed["created_at"],
            "temperatura": _float_seguro(feed.get("field1")),
            "umidade": _float_seguro(feed.get("field2")),
        })
    return leituras


def _float_seguro(valor):
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None
