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