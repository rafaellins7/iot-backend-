# busca a última leitura do ThingSpeak e grava no banco.
import time
from src import config, thingspeak_client, database


def main():
    print(f"Conectando no canal ThingSpeak {config.THINGSPEAK_CHANNEL_ID}...")
    print(f"Gravando em 'leitura_climatica' (sensor_id={config.SENSOR_ID}).")
    print(f"Iniciando polling a cada {config.POLL_INTERVAL_SECONDS}s (Ctrl+C pra parar)\n")

    ultimo_entry_id = None

    while True:
        try:
            leitura = thingspeak_client.buscar_ultima_leitura()

            if leitura is None:
                print("Canal ainda sem dados. Aguardando...")
            elif leitura["entry_id"] != ultimo_entry_id:
                status = database.processar_leitura(leitura)
                if status == "gravada":
                    print(
                        f"[OK] entry_id={leitura['entry_id']} "
                        f"temp={leitura['temperatura']} umid={leitura['umidade']} "
                        f"-> gravado no banco"
                    )
                elif status == "rejeitada":
                    print(
                        f"[REJEITADA] entry_id={leitura['entry_id']} "
                        f"-> registrada em leitura_rejeitada"
                    )
                ultimo_entry_id = leitura["entry_id"]
            else:
                print("Sem leitura nova ainda.")

        except Exception as e:
            print(f"[ERRO] {e}")

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
