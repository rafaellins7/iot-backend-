# Validação das leituras vindas do ThingSpeak antes de gravar em leitura_climatica.
# Retorna a lista de motivos de rejeição; lista vazia = leitura válida.
import math
from datetime import datetime
from typing import List

from src import config


def _data_valida(valor) -> bool:
    if not isinstance(valor, str) or not valor:
        return False
    try:
        datetime.fromisoformat(valor.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _validar_medida(nome: str, valor, bruto, minimo: float, maximo: float, unidade: str) -> List[str]:
    if valor is None:
        if bruto is None or str(bruto).strip() == "":
            return [f"{nome} ausente"]
        return [f"{nome} não numérica ({str(bruto)[:30]!r})"]
    if not math.isfinite(valor):
        return [f"{nome} inválida (NaN/infinito)"]
    if valor < minimo or valor > maximo:
        return [f"{nome} fora da faixa válida ({valor}{unidade}; aceito {minimo} a {maximo}{unidade})"]
    return []


def validar_leitura(leitura: dict) -> List[str]:
    motivos: List[str] = []

    if not isinstance(leitura.get("entry_id"), int):
        motivos.append("entry_id ausente ou inválido")

    if not _data_valida(leitura.get("created_at")):
        motivos.append("data/hora ausente ou em formato inválido")

    motivos += _validar_medida(
        "temperatura", leitura.get("temperatura"), leitura.get("temperatura_bruta"),
        config.TEMP_MIN_VALIDA, config.TEMP_MAX_VALIDA, "°C",
    )
    motivos += _validar_medida(
        "umidade", leitura.get("umidade"), leitura.get("umidade_bruta"),
        config.UMIDADE_MIN_VALIDA, config.UMIDADE_MAX_VALIDA, "%",
    )
    return motivos