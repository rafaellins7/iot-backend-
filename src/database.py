# Schema provisório até o Daniel fechar o definitivo.
import psycopg2
from src import config


def conectar():
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
    )


def criar_tabelas():
    sql = """
    CREATE TABLE IF NOT EXISTS leituras (
        id SERIAL PRIMARY KEY,
        entry_id_thingspeak INTEGER UNIQUE NOT NULL,
        temperatura REAL,
        umidade REAL,
        criado_em TIMESTAMPTZ NOT NULL,
        inserido_em TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def inserir_leitura(leitura: dict):
    sql = """
    INSERT INTO leituras (entry_id_thingspeak, temperatura, umidade, criado_em)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (entry_id_thingspeak) DO NOTHING;
    """
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (
                leitura["entry_id"],
                leitura["temperatura"],
                leitura["umidade"],
                leitura["created_at"],
            ))
            linhas_afetadas = cur.rowcount
        conn.commit()
    return linhas_afetadas > 0

