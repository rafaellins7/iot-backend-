import psycopg2
from src import config, validacao


def conectar():
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
    )


def inserir_leitura(leitura: dict, sensor_id: int = None):
    sensor_id = sensor_id or config.SENSOR_ID
    sql = """
    INSERT INTO leitura_climatica
        (fk_sensor_id_sensor, entry_id_thingspeak, temperatura, umidade,
         data_hora, data_recebimento, origem)
    VALUES (%s, %s, %s, %s, %s, now() AT TIME ZONE 'UTC', 'thingspeak')
    ON CONFLICT (fk_sensor_id_sensor, entry_id_thingspeak) DO NOTHING;
    """
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (
                sensor_id,
                leitura["entry_id"],
                leitura["temperatura"],
                leitura["umidade"],
                leitura["created_at"],
            ))
            linhas_afetadas = cur.rowcount
        conn.commit()
    return linhas_afetadas > 0

def _texto(valor, limite=100):
    return None if valor is None else str(valor)[:limite]


def registrar_leitura_rejeitada(leitura: dict, motivo: str, sensor_id: int = None):
    sensor_id = sensor_id or config.SENSOR_ID
    entry_id = leitura.get("entry_id")
    sql = """
    INSERT INTO leitura_rejeitada
        (fk_sensor_id_sensor, entry_id_thingspeak, temperatura_bruta, umidade_bruta,
         data_hora_bruta, motivo, origem, data_rejeicao)
    VALUES (%s, %s, %s, %s, %s, %s, 'thingspeak', now() AT TIME ZONE 'UTC')
    ON CONFLICT (fk_sensor_id_sensor, entry_id_thingspeak) DO NOTHING;
    """
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (
                sensor_id,
                entry_id if isinstance(entry_id, int) else None,
                _texto(leitura.get("temperatura_bruta")),
                _texto(leitura.get("umidade_bruta")),
                _texto(leitura.get("created_at")),
                motivo[:255],
            ))
            linhas_afetadas = cur.rowcount
        conn.commit()
    return linhas_afetadas > 0


def processar_leitura(leitura: dict, sensor_id: int = None) -> str:
    motivos = validacao.validar_leitura(leitura)
    if motivos:
        registrar_leitura_rejeitada(leitura, "; ".join(motivos), sensor_id)
        return "rejeitada"
    return "gravada" if inserir_leitura(leitura, sensor_id) else "duplicada"