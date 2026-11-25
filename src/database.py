import psycopg2
from src import config, validacao


def conectar():
    if config.DATABASE_URL:
        return psycopg2.connect(config.DATABASE_URL)
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
    )


def montar_insert_leitura(leitura: dict, sensor_id: int):
    """Monta o INSERT. Colunas de solo só entram quando a leitura as traz (TS_FIELD_* no .env)."""
    colunas = ["fk_sensor_id_sensor", "entry_id_thingspeak", "temperatura", "umidade"]
    valores = [sensor_id, leitura["entry_id"], leitura["temperatura"], leitura["umidade"]]
    for coluna in ("umidade_solo", "temperatura_solo"):
        if coluna in leitura:
            colunas.append(coluna)
            valores.append(leitura[coluna])
    colunas += ["data_hora", "data_recebimento", "origem"]
    valores.append(leitura["created_at"])
    marcadores = ", ".join(["%s"] * len(valores))
    sql = (
        f"INSERT INTO leitura_climatica ({', '.join(colunas)}) "
        f"VALUES ({marcadores}, now() AT TIME ZONE 'UTC', 'thingspeak') "
        "ON CONFLICT (fk_sensor_id_sensor, entry_id_thingspeak) DO NOTHING;"
    )
    return sql, valores


def inserir_leitura(leitura: dict, sensor_id: int = None):
    sensor_id = sensor_id or config.SENSOR_ID
    sql, valores = montar_insert_leitura(leitura, sensor_id)
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, valores)
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
    if inserir_leitura(leitura, sensor_id):
        try:
            from src.api.services import parecer_auto
            parecer_auto.agendar_por_sensor(sensor_id or config.SENSOR_ID)
        except Exception:
            pass
        return "gravada"
    return "duplicada"

import inspect


def get_db():
    """Compatibilidade: reaproveita a conexão do get_conn (src.api.deps)."""
    from src.api.deps import get_conn 
    resultado = get_conn()
    if inspect.isgenerator(resultado):
        yield from resultado
    else:
        yield resultado