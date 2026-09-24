# Backend - IoT ThingSpeak -> PostgreSQL

Lê os dados de temperatura/umidade do canal ThingSpeak e grava no PostgreSQL.

## 1. Criar e ativar o ambiente virtual

```bash
python3 -m venv venv

# Linux/Mac
source venv/bin/activate

# Windows (PowerShell)
venv\Scripts\Activate.ps1
```

## 2. Instalar as dependências

```bash
pip install -r requirements.txt
```

## 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Abra o `.env` e confira:
- `THINGSPEAK_CHANNEL_ID`
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: dados de conexão do PostgreSQL (local ou o que o Daniel configurar)

Se o banco `iot_db` ainda não existir, crie-o (com o Postgres rodando localmente):

```bash
createdb iot_db
# ou, dentro do psql:
# CREATE DATABASE iot_db;
```

## 4. Rodar

**Opção A — importar o histórico recente de uma vez (bom pra testar rápido):**
```bash
python -m scripts.backfill_historico
```

**Opção B — rodar o loop contínuo (fica escutando e grava toda leitura nova):**
```bash
python -m src.main
```

## Estrutura

```
iot-backend/
├── requirements.txt
├── .env.example
├── src/
│   ├── config.py            # lê as variáveis do .env
│   ├── thingspeak_client.py # busca dados na API do ThingSpeak
│   ├── database.py          # conexão e escrita no PostgreSQL
│   └── main.py              # loop principal (polling)
└── scripts/
    └── backfill_historico.py  # importa histórico de uma vez
```

## Sobre o schema do banco

A tabela `leituras` criada em `database.py` é um schema inicial só pra
destravar o desenvolvimento.

Colunas atuais de `leituras`:
| coluna                 | tipo         | descrição                                   |
|-------------------------|--------------|----------------------------------------------|
| id                      | serial (PK)  | id interno                                    |
| entry_id_thingspeak     | integer (UQ) | id da leitura no ThingSpeak (evita duplicata) |
| temperatura             | real         | field1 do canal                               |
| umidade                 | real         | field2 do canal                               |
| criado_em               | timestamptz  | timestamp de quando o ESP32 enviou            |
| inserido_em             | timestamptz  | timestamp de quando foi gravado no banco      |

