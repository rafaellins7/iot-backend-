# Raiz - Backend

Backend do **Raiz**, uma plataforma de monitoramento agrícola por sensores. Reúne dois programas que compartilham o mesmo banco PostgreSQL:

* um **serviço de ingestão** que lê o canal ThingSpeak (ESP32/DHT11), valida e grava as leituras;
* uma **API REST (FastAPI)** que alimenta o dashboard: sensores, lotes, leituras, alertas, faixas ideais, mercado, viagens, riscos, relatórios, usuários e auditoria.

> **Projeto em desenvolvimento.** A API já cobre a maior parte do dashboard, mas **ainda não tem login nem controle de acesso: nenhuma rota exige autenticação** (veja [Autenticação e Segurança](#autenticação-e-segurança)). Estrutura e banco podem mudar. Este README reflete o estado atual do código.

## Fluxo

```text
ESP32 / DHT11
      |
  ThingSpeak ──► Serviço de ingestão (polling + validação) ──┐
                                                             ▼
  Open-Meteo ──► API FastAPI  ◄──────────────────────►  PostgreSQL
                      |                                  (repo iot_db)
                  Dashboard
```

## Tecnologias

| Camada | Tecnologia |
| ------ | ---------- |
| API | Python, FastAPI, Uvicorn, Pydantic |
| Banco | PostgreSQL, psycopg2-binary (SQL direto, sem ORM) |
| Integrações | ThingSpeak REST API, Open-Meteo (previsão do tempo) |
| Segurança | bcrypt |
| Configuração | python-dotenv |

## Estrutura

```text
iot-backend/
├── src/
│   ├── api/
│   │   ├── routers/            # um arquivo por recurso
│   │   ├── app.py              # FastAPI, CORS e registro dos routers
│   │   ├── auditoria.py        # registro de ações em log_acesso
│   │   ├── deps.py             # conexão por requisição
│   │   ├── filtros.py          # filtros de período e validação de sensor
│   │   ├── schemas.py          # modelos Pydantic
│   │   └── security.py         # hash e verificação de senha
│   ├── config.py               # variáveis de ambiente
│   ├── database.py             # conexão e gravação das leituras
│   ├── main.py                 # loop de ingestão
│   ├── open_meteo_client.py    # cliente da Open-Meteo
│   ├── thingspeak_client.py    # cliente do ThingSpeak
│   └── validacao.py            # regras de validação das leituras
├── scripts/
│   └── backfill_historico.py   # importa leituras antigas do canal
├── .env.example
└── requirements.txt
```

## Ingestão de dados

O serviço (`python -m src.main`) consulta a última leitura do canal a cada `POLL_INTERVAL_SECONDS` (padrão 20 s). Para cada leitura nova:

1. **Valida** (`src/validacao.py`): `entry_id` inteiro, data em ISO 8601, temperatura e umidade presentes, numéricas, finitas e dentro das faixas `TEMP_*_VALIDA` e `UMIDADE_*_VALIDA`.
2. **Grava** em `leitura_climatica` se for válida. A deduplicação é feita pelo banco (`ON CONFLICT (sensor, entry_id_thingspeak) DO NOTHING`).
3. **Rejeita** se for inválida: guarda os valores brutos e o motivo em `leitura_rejeitada`, sem perder o dado.

Mapeamento do canal: `field1` = temperatura, `field2` = umidade. Todas as leituras vão para o sensor definido em `SENSOR_ID`, então um serviço de ingestão atende **um canal e um sensor**. Os alertas de faixa são criados pelo trigger do banco, não por este código.

O script `scripts/backfill_historico.py` faz o mesmo processamento com as últimas 100 leituras do canal e imprime quantas foram gravadas, duplicadas e rejeitadas.

## API

Documentação interativa (Swagger) em `/docs` com a API rodando. Todas as listagens com `limit` aceitam até 1000 (padrão 100) e `offset`. Parâmetros `inicio` e `fim` são ISO 8601; sem fuso, são tratados como **UTC**.

| Recurso | Rotas | Observações |
| ------- | ----- | ----------- |
| **Usuários** | `GET /usuarios` (`?status=`), `GET /usuarios/{id}`, `POST`, `PUT /usuarios/{id}`, `DELETE /usuarios/{id}`, `PUT /usuarios/{id}/senha` | `DELETE` só marca como `inativo`. Troca de senha exige a senha atual. |
| **Perfis** | `GET /perfis` | |
| **Sensores** | `GET /sensores` (`?ambiente=&id_lote=&status=`), `GET /sensores/{id}`, `POST`, `PUT /sensores/{id}`, `DELETE /sensores/{id}`, `GET /sensores/{id}/leituras?periodo=24h\|7d\|30d` | `DELETE` só marca como `inativo`. `channel_id` é único. O endpoint de leituras devolve médias por hora (24h e 7d) ou por dia (30d, dia civil em `America/Recife`) e indica se o ponto é `real` ou `simulado`. |
| **Leituras** | `GET /leituras` (`?id_sensor=&inicio=&fim=`), `GET /leituras/ultima`, `GET /leituras/estatisticas`, `GET /leituras/{id}` | Estatísticas: total, primeira/última, mín., máx. e média. |
| **Leituras rejeitadas** | `GET /leituras-rejeitadas` (`?id_sensor=&motivo=&inicio=&fim=`), `GET /leituras-rejeitadas/{id}` | |
| **Lotes** | `GET /lotes` (`?status=&id_fruta=`), `GET /lotes/{id}`, `POST`, `PATCH /lotes/{id}` | Inclui a `etapa` do lote (campo, armazenamento ou transporte). |
| **Frutas** | `GET /frutas`, `GET /frutas/{id}` | |
| **Faixas ideais** | `GET /config-parametros` (`?id_fruta=&etapa=`), `GET /{id}`, `POST`, `PUT /{id}` | Uma faixa por fruta e etapa; exige mín. < máx. |
| **Alertas** | `GET /alertas` (`?status=&nivel=&id_sensor=&id_lote=`), `GET /alertas/{id}`, `PATCH /alertas/{id}/status` | Datas em ISO 8601 com `Z`. |
| **Dados de mercado** | `GET /dados-mercado` (`?id_fruta=&inicio=&fim=`), `GET /{id}`, `POST`, `PATCH /{id}` | |
| **Dashboard** | `GET /dashboard/resumo` | Cartões: sensores ativos (reais e simulados), lotes monitorados, alertas abertos, condição geral, % das leituras na faixa nas últimas 24 h, médias do ar e VPD, fluxo dos lotes por etapa. |
| **Relatórios** | `GET /relatorios/saidas-faixa` (`?agrupamento=dia\|semana\|mes&id_lote=&id_sensor=&inicio=&fim=`) | Leituras fora da faixa ideal por período. |
| **Viagens** | `GET /viagens` (`?status=`), `GET /viagens/{id}` | Progresso, ETA, atraso e posição **estimada** sobre o traçado da rota, mais o risco mais recente do lote. |
| **Riscos** | `GET /riscos/prejuizo`, `GET /riscos/climatico` (`?id_lote=&nivel=&limite=`) | Sem `id_lote`: última previsão de cada lote. Com `id_lote`: histórico. |
| **Clima** | `GET /clima/previsao` (`?dias=1-7&latitude=&longitude=`) | Previsão da Open-Meteo, com cache em memória. |
| **Auditoria** | `GET /auditoria` (`?id_usuario=&acao=&resultado=&inicio=&fim=`), `GET /auditoria/{id}` | |

**Auditoria:** criar/editar/desativar usuários e sensores, criar/editar lotes, faixas ideais e dados de mercado, e trocar senha gravam em `log_acesso` (ação, IP, resultado de sucesso ou falha). Como ainda não há login, o usuário só é registrado na troca de senha.

**Dados da Open-Meteo:** ao exibir a previsão na interface, cite a Open-Meteo (termos de uso em <https://open-meteo.com/en/features#terms>).

## Autenticação e Segurança

Já implementado:

* Senhas com hash **bcrypt**; tamanho de 8 a 72 caracteres e validação de e-mail;
* E-mail único (sem diferenciar maiúsculas) e desativação em vez de exclusão de usuários e sensores;
* Consultas SQL parametrizadas e campos editáveis restritos a uma lista fixa;
* Registro de auditoria que nunca derruba a requisição se falhar;
* CORS restrito às origens de `CORS_ORIGINS`.

Ainda **não** implementado: login com token, controle de acesso por perfil (RBAC) e proteção das rotas. **Hoje qualquer cliente que alcance a API pode ler e alterar dados**, incluindo usuários. Não exponha a API publicamente até isso existir.

Segredos (`.env`, chaves, senhas) não devem ser versionados.

## Banco de Dados

O banco fica em outro repositório: <https://github.com/LorenaLira05/iot_db>. Este backend **não cria nem altera o banco**: ele se conecta a um banco já preparado com os scripts de lá.

Rode, na ordem: `schema.sql`, `restricoes.sql`, `seed.sql`, `triggers.sql`, `views.sql`. Para os endpoints de **riscos** e **viagens** rode também `implementação_ia.sql` (tabelas de modelos e previsões).

O código usa:

| Objeto | Usado por |
| ------ | --------- |
| `leitura_climatica`, `leitura_rejeitada`, `sensor` | ingestão, sensores, leituras |
| `usuario`, `perfil`, `log_acesso` | usuários, perfis, auditoria |
| `lote`, `fruta`, `config_parametro`, `dados_mercado` | lotes, frutas, faixas, mercado |
| `alerta` | alertas (criados pelo trigger `trg_alerta_faixa`) |
| `viagem`, `porto`, `rota`, `previsao_prejuizo`, `risco_climatico`, `ia_modelo` | viagens e riscos |
| `fn_etapa_lote()`, `vw_lote_saude` | lotes, dashboard, relatórios |

O `seed.sql` não cadastra rotas, viagens nem previsões de IA; sem esses dados, `/viagens` e `/riscos/*` retornam listas vazias. Se o esquema do banco mudar, este backend precisará acompanhar.

## Como Executar

### 1. Clonar o repositório

```bash
git clone https://github.com/rafaellins7/iot-backend-.git
cd iot-backend-
```

### 2. Criar ambiente virtual

```bash
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Configurar o `.env`

Copie `.env.example` para `.env` e preencha:

| Variável | Descrição | Padrão |
| -------- | --------- | ------ |
| `THINGSPEAK_CHANNEL_ID` | ID do canal | — |
| `THINGSPEAK_READ_API_KEY` | Chave de leitura (só para canal privado) | vazio |
| `POLL_INTERVAL_SECONDS` | Intervalo da coleta, em segundos | `20` |
| `SENSOR_ID` | `id_sensor` que recebe as leituras do canal | `1` |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Conexão com o PostgreSQL | — |
| `CLIMA_LATITUDE`, `CLIMA_LONGITUDE` | Coordenadas padrão de `/clima/previsao` (sem elas a rota responde 503, a menos que a requisição envie as coordenadas) | — |
| `CLIMA_TIMEZONE` | Fuso usado na previsão e na agregação diária | `America/Recife` |
| `CLIMA_CACHE_SEGUNDOS` | Validade do cache da previsão | `600` |
| `CORS_ORIGINS` | Origens liberadas, separadas por vírgula | `localhost`/`127.0.0.1` nas portas 5173 e 5174 |
| `TEMP_MIN_VALIDA`, `TEMP_MAX_VALIDA` | Faixa aceita de temperatura (°C) | `-40` e `80` |
| `UMIDADE_MIN_VALIDA`, `UMIDADE_MAX_VALIDA` | Faixa aceita de umidade (%) | `0` e `100` |

### 5. Preparar o banco

Veja [Banco de Dados](#banco-de-dados). Depois, use os dados de conexão no `.env`.

### 6. Executar

**Coleta contínua** (grava toda leitura nova do ThingSpeak):

```bash
python -m src.main
```

**Importar histórico** (últimas 100 leituras do canal):

```bash
python -m scripts.backfill_historico
```

**API:**

```bash
uvicorn src.api.app:app --reload
```

Disponível em `http://127.0.0.1:8000`, com a documentação em `/docs`. A coleta e a API são processos independentes: rode os dois para ter dados novos chegando enquanto o dashboard está aberto.

## Status do Projeto

### Implementado

* [x] API FastAPI organizada por routers
* [x] Ingestão do ThingSpeak com validação, deduplicação e log de leituras rejeitadas
* [x] Importação de histórico
* [x] Usuários e perfis, com bcrypt e desativação lógica
* [x] Sensores (ar e solo), lotes, frutas e faixas ideais
* [x] Consulta de leituras, estatísticas e séries agregadas por sensor
* [x] Alertas (consulta e atualização de status)
* [x] Dashboard, relatório de saídas de faixa e dados de mercado
* [x] Viagens com posição estimada, e riscos (prejuízo e climático)
* [x] Previsão do tempo (Open-Meteo)
* [x] Auditoria de ações

### Em desenvolvimento / A fazer

* [ ] Login e autenticação 2f
* [ ] Controle de acesso por perfil (RBAC)
* [ ] Proteção das rotas existentes
* [ ] Ingestão de vários sensores/canais e dos campos de solo
* [ ] Endpoints para gerar previsões (hoje a API só consulta as já gravadas)
* [ ] Recuperação de senha
* [ ] Testes automatizados
* [ ] Implementação de IA
* [ ] Envio de alertas pelo Whatsapp/Telegram
* [ ] Logs estruturados em vez de `print`
* [ ] Deploy

## Licença

Projeto acadêmico.
