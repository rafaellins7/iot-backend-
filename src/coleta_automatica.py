"""Coleta do ThingSpeak em segundo plano, dentro do lifespan da API (src/api/app.py).

Reaproveita main.ciclo_coleta (bloqueante, por isso roda em asyncio.to_thread).
Só um processo coleta por vez: um advisory lock do Postgres, preso por uma conexão dedicada,
vale para uvicorn --reload e para vários workers. Quem não tem o lock tenta de novo a cada
ciclo, então se o processo que coleta cair (ou reiniciar com --reload) outro assume sozinho.
"""
import asyncio
import logging

from src import config, database
from src.main import ciclo_coleta

log = logging.getLogger("coleta")

LOCK_KEY = 727001  # chave arbitrária do advisory lock


def _obter_lock(conn_atual):
    """Devolve a conexão que segura o lock, ou None se outro processo coleta."""
    if conn_atual is not None:
        try:
            with conn_atual.cursor() as cur:
                cur.execute("SELECT 1")
            return conn_atual
        except Exception:
            log.warning("Conexão do lock de coleta caiu; tentando obter de novo")
            try:
                conn_atual.close()
            except Exception:
                pass
    conn = database.conectar()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            if cur.fetchone()[0]:
                return conn
    except Exception:
        conn.close()
        raise
    conn.close()
    return None


async def _loop():
    estado = {"ultimo_entry_id": None}
    lock_conn = None
    avisou = False
    try:
        while True:
            try:
                tinha_lock = lock_conn is not None
                lock_conn = await asyncio.to_thread(_obter_lock, lock_conn)
                if lock_conn is None:
                    if not avisou:
                        log.info("Outro processo já está coletando; este não coleta (tenta de novo a cada ciclo)")
                        avisou = True
                else:
                    if not tinha_lock:
                        avisou = False
                        msg = (f"Coleta ThingSpeak iniciada: canal {config.THINGSPEAK_CHANNEL_ID}, "
                               f"intervalo {config.POLL_INTERVAL_SECONDS} s, sensor {config.SENSOR_ID}")
                        print(msg, flush=True)
                        log.info(msg)
                    await asyncio.to_thread(ciclo_coleta, estado)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Erro no ciclo de coleta (seguindo para o próximo)")
            await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
    finally:
        if lock_conn is not None:
            try:
                lock_conn.close()  # fechar a conexão libera o advisory lock
            except Exception:
                pass


def iniciar():
    """Cria a tarefa de coleta (ou devolve None se COLETA_AUTOMATICA=false)."""
    if not config.COLETA_AUTOMATICA:
        log.info("Coleta automática desligada (COLETA_AUTOMATICA=false)")
        return None
    return asyncio.create_task(_loop(), name="coleta-thingspeak")


async def parar(task):
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
