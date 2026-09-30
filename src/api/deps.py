from src import database


def get_conn():
    """Abre uma conexão por requisição e garante rollback/fechamento.
    O commit é feito explicitamente em cada endpoint que grava."""
    conn = database.conectar()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()