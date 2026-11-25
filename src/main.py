# Busca a última leitura do ThingSpeak e grava no banco.
import logging
import time
from src import config, thingspeak_client, database
from src import agendador
from src.api.services import notificacao

log = logging.getLogger("coleta")


def ciclo_coleta(estado: dict) -> None:
    """Um ciclo de coleta (bloqueante): busca a última leitura, grava e processa notificações.
    `estado` guarda o último entry_id visto. Nunca levanta exceção: erro vira log."""
    try:
        leitura = thingspeak_client.buscar_ultima_leitura()

        if leitura is None:
            log.info("Canal ainda sem dados. Aguardando...")
        elif leitura["entry_id"] != estado.get("ultimo_entry_id"):
            status = database.processar_leitura(leitura)
            if status == "gravada":
                log.info(
                    "Leitura gravada: entry_id=%s temp=%s umid=%s solo=%s",
                    leitura["entry_id"], leitura["temperatura"], leitura["umidade"],
                    leitura.get("umidade_solo"),
                )
            elif status == "rejeitada":
                log.warning("Leitura rejeitada: entry_id=%s (registrada em leitura_rejeitada)",
                            leitura["entry_id"])
            else:
                log.info("Leitura duplicada ignorada: entry_id=%s", leitura["entry_id"])
            estado["ultimo_entry_id"] = leitura["entry_id"]
        else:
            log.debug("Sem leitura nova ainda.")

    except Exception:
        log.exception("Erro na coleta do ThingSpeak")

    if config.NOTIFICACAO_ATIVA:
        try:
            r = notificacao.processar_alertas_pendentes()
            if r["enviado"] or r["falha"]:
                log.info("Notificações: %s", r)
        except Exception:
            log.exception("Erro ao processar notificações")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"Conectando no canal ThingSpeak {config.THINGSPEAK_CHANNEL_ID}...")
    print(f"Gravando em 'leitura_climatica' (sensor_id={config.SENSOR_ID}).")
    print(f"Iniciando polling a cada {config.POLL_INTERVAL_SECONDS}s (Ctrl+C pra parar)\n")

    estado = {"ultimo_entry_id": None}

    agendador.iniciar_em_segundo_plano()  # risco, janela, irrigação, prejuízo, preditivos e IA

    while True:
        ciclo_coleta(estado)
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
