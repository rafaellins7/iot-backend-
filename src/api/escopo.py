"""Escopo de dados por dono (proteção contra IDOR / BOLA).

Regra do projeto:
  * Produtor/Exportador enxerga e opera SOMENTE os sensores e lotes em que
    `fk_usuario_id_usuario` é o id dele (vem do token, nunca da requisição).
  * Administrador e Analista de Dados têm escopo total (análise entre lotes/safras).

Leituras, leituras rejeitadas e alertas não têm dono próprio: herdam o dono do sensor.

Recurso de outro dono responde 404 (e não 403), igual a um id inexistente,
para não revelar que o recurso existe.
"""
from typing import Optional

from fastapi import HTTPException

from . import seguranca_log
from .deps_auth import ADMIN, ANALISTA

PERFIS_ESCOPO_TOTAL = {ADMIN.lower(), ANALISTA.lower()}


def nao_encontrado(user, recurso: str, ident, mensagem: str) -> HTTPException:
    """404 para recurso inexistente OU de outro dono (indistinguíveis). Loga a tentativa de IDOR
    quando o usuário tem escopo restrito (com o código de missão)."""
    if id_dono(user) is not None:
        seguranca_log.bloqueio("IDOR", f"acesso_a_{recurso}_de_outro_dono_ou_inexistente", user["id_usuario"], id_solicitado=ident)
    return HTTPException(status_code=404, detail=mensagem)


def id_dono(user) -> Optional[int]:
    """None = escopo total. Inteiro = restrito aos recursos desse usuário."""
    if user["perfil"].lower() in PERFIS_ESCOPO_TOTAL:
        return None
    return user["id_usuario"]


def filtrar_por_dono(user, coluna: str, where: list, params: list) -> None:
    """Acrescenta `coluna = <id do token>` quando o perfil é restrito."""
    dono = id_dono(user)
    if dono is not None:
        where.append(f"{coluna} = %s")
        params.append(dono)


def filtrar_leituras_por_dono(user, coluna_sensor: str, where: list, params: list) -> None:
    """Para tabelas que apontam para o sensor (leitura_climatica, leitura_rejeitada)."""
    dono = id_dono(user)
    if dono is not None:
        where.append(f"{coluna_sensor} IN (SELECT id_sensor FROM sensor WHERE fk_usuario_id_usuario = %s)")
        params.append(dono)


def _exigir(cur, user, tabela: str, coluna_id: str, valor: Optional[int], mensagem: str) -> None:
    if valor is None:
        return
    sql = f"SELECT 1 FROM {tabela} WHERE {coluna_id} = %s"
    params = [valor]
    dono = id_dono(user)
    if dono is not None:
        sql += " AND fk_usuario_id_usuario = %s"
        params.append(dono)
    cur.execute(sql, params)
    if cur.fetchone() is None:
        raise nao_encontrado(user, tabela, valor, mensagem)


def exigir_sensor(cur, user, id_sensor: Optional[int]) -> None:
    _exigir(cur, user, "sensor", "id_sensor", id_sensor, "Sensor não encontrado")


def exigir_lote(cur, user, id_lote: Optional[int]) -> None:
    _exigir(cur, user, "lote", "id_lote", id_lote, "Lote não encontrado")
