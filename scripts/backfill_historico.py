# Importa de uma vez as últimas leituras do canal pro banco.
from src import thingspeak_client, database


def main(quantidade=100):
    leituras = thingspeak_client.buscar_leituras(quantidade=quantidade)

    if not leituras:
        print("Nenhuma leitura encontrada no canal ainda.")
        return

    contagem = {"gravada": 0, "duplicada": 0, "rejeitada": 0}
    for leitura in leituras:
        contagem[database.processar_leitura(leitura)] += 1

    print(f"Processadas {len(leituras)} leituras do ThingSpeak: "
          f"{contagem['gravada']} novas gravadas, "
          f"{contagem['duplicada']} já existiam, "
          f"{contagem['rejeitada']} rejeitadas (veja a tabela leitura_rejeitada).")


if __name__ == "__main__":
    main()