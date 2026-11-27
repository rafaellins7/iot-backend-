import threading
import time

import psycopg2
from psycopg2 import extensions, pool

from src import config, database

_pool_lock = threading.Lock()
_conn_pool = None
_last_used: dict[int, float] = {}
_IDLE_CHECK_SECONDS = 120.0


def _get_pool():
    global _conn_pool
    if _conn_pool is not None:
        return _conn_pool
    with _pool_lock:
        if _conn_pool is None:
            kwargs = {
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }
            if config.DATABASE_URL:
                _conn_pool = pool.ThreadedConnectionPool(1, 10, dsn=config.DATABASE_URL, **kwargs)
            else:
                _conn_pool = pool.ThreadedConnectionPool(
                    1,
                    10,
                    host=config.DB_HOST,
                    port=config.DB_PORT,
                    dbname=config.DB_NAME,
                    user=config.DB_USER,
                    password=config.DB_PASSWORD,
                    **kwargs,
                )
    return _conn_pool


def _adquirir_conexao():
    p = _get_pool()
    conn = p.getconn()
    conn_id = id(conn)
    agora = time.monotonic()

    if conn.closed:
        _last_used.pop(conn_id, None)
        p.putconn(conn, close=True)
        conn = p.getconn()
        conn_id = id(conn)

    # Se ficou ociosa por mais de 2 min, valida se o Neon não encerrou o socket
    ultimo_uso = _last_used.get(conn_id, agora)
    if (agora - ultimo_uso) > _IDLE_CHECK_SECONDS:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            if conn.info.transaction_status != extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            _last_used.pop(conn_id, None)
            try:
                p.putconn(conn, close=True)
            except Exception:
                pass
            conn = p.getconn()
    return conn


def get_conn():
    """Obtém conexão do pool (com fallback seguro) e garante rollback/devolução limpa.
    O commit é feito explicitamente em cada endpoint que grava."""
    usando_pool = True
    try:
        conn = _adquirir_conexao()
    except Exception:
        usando_pool = False
        conn = database.conectar()

    try:
        yield conn
    except Exception:
        if not conn.closed:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if not usando_pool:
            try:
                conn.close()
            except Exception:
                pass
            return

        p = _conn_pool
        if p is None:
            try:
                conn.close()
            except Exception:
                pass
            return

        conn_id = id(conn)
        if conn.closed:
            _last_used.pop(conn_id, None)
            try:
                p.putconn(conn, close=True)
            except Exception:
                pass
        else:
            try:
                if conn.info.transaction_status != extensions.TRANSACTION_STATUS_IDLE:
                    conn.rollback()
                _last_used[conn_id] = time.monotonic()
                p.putconn(conn)
            except Exception:
                _last_used.pop(conn_id, None)
                try:
                    p.putconn(conn, close=True)
                except Exception:
                    pass
