"""Gatilho automático de geração de parecer com debounce e lock anti-duplicação.
Disparado quando novas leituras reais são inseridas no banco.
"""

import logging
import os
import threading
from typing import Dict, Optional

log = logging.getLogger(__name__)

_DEBOUNCE_SEGUNDOS = int(os.getenv("PARECER_DEBOUNCE_S", "30"))

_timers: Dict[int, threading.Timer] = {}
_lock = threading.Lock()


def _usuario_sistema():
    """Identidade de sistema para execuções automáticas em background."""
    from src.api.deps_auth import ADMIN
    return {
        "id_usuario": None,
        "nome": "gatilho_automatico",
        "email": None,
        "perfil": ADMIN,
        "ativo": True,
        "deve_trocar_senha": False,
    }


def _disparar_geracao_lote(id_lote: int):
    """Executado quando o tempo de debounce se esgota."""
    with _lock:
        _timers.pop(id_lote, None)

    try:
        from src import database
        from src.api.routers import pareceres

        log.info("[PARECER_AUTO] Executando geração automática para lote %s...", id_lote)
        with database.conectar() as conn:
            res = pareceres.executar_geracao_parecer(
                conn=conn,
                id_lote=id_lote,
                tipo="agronomico",
                dias=30,
                forcar=False,
                user=_usuario_sistema(),
                request=None,
            )
            reaprov = res.get("reaproveitado", False)
            status = res.get("status", "desconhecido")
            log.info(
                "[PARECER_AUTO] Lote %s finalizado: status=%s, reaproveitado=%s",
                id_lote, status, reaprov
            )
    except Exception as e:
        log.error("[PARECER_AUTO] Falha na geração automática do lote %s: %s", id_lote, e)


def agendar_por_lote(id_lote: int, debounce_segundos: Optional[int] = None):
    """Agenda geração com debounce para o lote. Se novas leituras chegarem, reinicia o timer."""
    if not id_lote:
        return

    intervalo = debounce_segundos if debounce_segundos is not None else _DEBOUNCE_SEGUNDOS

    with _lock:
        timer_existente = _timers.get(id_lote)
        if timer_existente and timer_existente.is_alive():
            timer_existente.cancel()

        novo_timer = threading.Timer(intervalo, _disparar_geracao_lote, args=[id_lote])
        novo_timer.daemon = True
        _timers[id_lote] = novo_timer
        novo_timer.start()

    log.debug("[PARECER_AUTO] Agendado para lote %s em %ss (debounce)", id_lote, intervalo)


def agendar_por_sensor(sensor_id: int):
    """Identifica o lote do sensor e enfileira o debounce."""
    if not sensor_id:
        return

    try:
        from src import database
        with database.conectar() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT fk_lote_id_lote FROM sensor WHERE id_sensor = %s", (sensor_id,))
                linha = cur.fetchone()
                if linha:
                    # Suporta tupla ou dicionário
                    id_lote = linha["fk_lote_id_lote"] if isinstance(linha, dict) else linha[0]
                    if id_lote:
                        agendar_por_lote(id_lote)
    except Exception as e:
        log.warning("[PARECER_AUTO] Erro ao buscar lote para sensor %s: %s", sensor_id, e)
