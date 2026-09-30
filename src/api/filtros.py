# Helpers compartilhados pelos endpoints de consulta (leituras, rejeitadas, auditoria).
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException


def normalizar_dt(valor: Optional[datetime]) -> Optional[datetime]:
    """O banco guarda TIMESTAMP sem fuso, em UTC. Se o cliente mandar um horário
    com fuso (ex.: ...Z ou -03:00), converte para UTC e tira o fuso."""
    if valor is not None and valor.tzinfo is not None:
        return valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


def montar_where(
    coluna_data: str,
    inicio: Optional[datetime],
    fim: Optional[datetime],
    where: List[str],
    params: list,
) -> None:
    """Acrescenta o filtro de período (inicio <= data <= fim) em where/params."""
    inicio, fim = normalizar_dt(inicio), normalizar_dt(fim)
    if inicio and fim and inicio > fim:
        raise HTTPException(status_code=400, detail="'inicio' não pode ser maior que 'fim'")
    if inicio:
        where.append(f"{coluna_data} >= %s")
        params.append(inicio)
    if fim:
        where.append(f"{coluna_data} <= %s")
        params.append(fim)


def clausula(where: List[str]) -> str:
    return (" WHERE " + " AND ".join(where)) if where else ""


def garantir_sensor(cur, id_sensor: Optional[int]) -> None:
    if id_sensor is None:
        return
    cur.execute("SELECT 1 FROM sensor WHERE id_sensor = %s", (id_sensor,))
    if cur.fetchone() is None:
        raise HTTPException(status_code=404, detail="Sensor não encontrado")