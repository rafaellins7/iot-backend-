# Importa de uma vez as últimas leituras do canal pro banco.
from src import thingspeak_client, database


def main(quantidade=100):
    database.criar_tabelas()
    leituras = thingspeak_client.buscar_leituras(quantidade=quantidade)

    if not leituras:
        print("Nenhuma leitura encontrada no canal ainda.")
        return

    novas = 0
    for leitura in leituras:
        if database.inserir_leitura(leitura):
            novas += 1

    print(f"Processadas {len(leituras)} leituras do ThingSpeak. "
          f"{novas} eram novas e foram gravadas no banco.")


if __name__ == "__main__":
    main()
