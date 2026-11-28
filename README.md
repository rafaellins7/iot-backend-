<div align="center">

# 🌱 Raiz — Backend

**Monitoramento climático e logístico em nuvem para exportadoras de frutas**
Sensores IoT → validação → PostgreSQL → API segura → dashboard com alertas, previsões e pareceres de IA.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![IoT](https://img.shields.io/badge/ESP32-ThingSpeak-E7352C?logo=espressif&logoColor=white)
![Gemini](https://img.shields.io/badge/IA-Gemini-8E75B2?logo=googlegemini&logoColor=white)
![Testes](https://img.shields.io/badge/testes-pytest-0A9EDC?logo=pytest&logoColor=white)
![Status](https://img.shields.io/badge/status-em%20desenvolvimento-orange)

</div>

---

## Sobre o projeto

O **Raiz** é a plataforma desenvolvida no Projeto Integrador do 4º módulo de Análise e Desenvolvimento de Sistemas (Senac) para acompanhar, em tempo real, as condições de lotes de frutas exportadas, do campo ao transporte. O foco é a região do Vale do São Francisco (Petrolina/Juazeiro).

Este repositório é o **backend**. Ele reúne dois programas independentes que compartilham o mesmo banco PostgreSQL:

| Programa | O que faz | Comando |
| -------- | --------- | ------- |
| **Serviço de ingestão + agendador** | Lê o ThingSpeak, valida e grava as leituras. Em segundo plano, gera risco climático, janela de colheita, irrigação, prejuízo, alertas preditivos e pareceres de IA. | `python -m src.main` |
| **API REST (FastAPI)** | Autenticação, controle de acesso por perfil e todos os dados que o dashboard consome. | `uvicorn src.api.app:app --reload` |

## Destaques

-  **Ingestão robusta:** validação de faixa, deduplicação pelo banco e log de leituras rejeitadas (nenhum dado bruto se perde).
-  **Ar e solo:** temperatura e umidade do ar (DHT11) e umidade do solo (ADC capacitivo), com mapeamento configurável dos *fields* do ThingSpeak.
-  **Alertas em duas camadas:** alertas de faixa (trigger no banco) e **alertas preditivos** a partir do risco climático, com central de alertas e exportação em CSV.
-  **IA aplicada:** pareceres automáticos por lote via LLM (Gemini), com cache por validade, modelos de reserva, *retry* e auditoria.
-  **Previsões:** janela de colheita, risco climático, prejuízo estimado e recomendação de irrigação, com dados da Open-Meteo.
-  **Segurança de verdade:** JWT + refresh, 2FA por **TOTP** (com códigos de recuperação) ou e-mail, bloqueio por tentativas, argon2id e proteção contra **IDOR/BOLA**.
-  **3 perfis:** Administrador, Analista de Dados e Produtor/Exportador, cada um com seu escopo.
-  **Tempo real:** stream SSE para o dashboard, com ticket de uso único.
-  **Auditoria:** ações sensíveis registradas em `log_acesso`.
-  **106 testes automatizados** (pytest), incluindo IDOR, permissões, TOTP e agendador.

##  Arquitetura

```text
 ESP32-C3 + DHT11 + sensor de solo
            │  MQTT / HTTP
            ▼
       ThingSpeak ──────────► Serviço de ingestão (python -m src.main)
                               ├─ polling + validação + deduplicação
                               ├─ notificações por e-mail
                               └─ agendador (thread em segundo plano)
                                   risco · janela · irrigação · prejuízo
                                   alertas preditivos · parecer de IA
                                          │
   Open-Meteo ───────────────────────────►│
   Gemini (LLM) ─────────────────────────►│
                                          ▼
                                    PostgreSQL  (repo iot_db)
                                          ▲
                                          │
                              API FastAPI (JWT + RBAC + escopo por dono)
                                          ▲
                                          │  REST + SSE
                                  Dashboard (React)
```

## Tecnologias

| Camada | Tecnologia |
| ------ | ---------- |
| API | Python, FastAPI, Uvicorn, Pydantic |
| Banco | PostgreSQL, psycopg2 (SQL direto, sem ORM) |
| Integrações | ThingSpeak, Open-Meteo, Google Gemini |
| Segurança | argon2id (bcrypt legado aceito), PyJWT, pyotp (TOTP), cryptography (Fernet), qrcode |
| E-mail | SMTP (ativação de conta, 2FA, recuperação de senha, alertas e relatórios) |
| Testes | pytest, coleção Postman (`qa-api/`) |

##  Perfis e permissões

O Administrador passa por todas as regras. Os demais seguem a tabela:

| Recurso | Produtor/Exportador | Analista de Dados |
| ------- | :-----------------: | :---------------: |
| Leituras, lotes, frutas, riscos, previsões, dashboard | 👁️ leitura, só dos próprios dados | 👁️ leitura |
| Sensores, faixas ideais, alertas, catálogo, central de alertas | 👁️ leitura | ✏️ lê e edita (sem excluir) |
| Pareceres | ✏️ consulta e gera | ✏️ consulta e gera |
| Dados de mercado, recomendações, IA (`/ia/*`) | 👁️ somente Produtor | ❌ |
| Resumos agregados, calibração, relatórios gerados | ❌ | ✅ |
| Usuários, perfis, auditoria | ❌ | ❌ (só Administrador) |

> Nos recursos acessados pelo Produtor, o servidor aplica **escopo por dono**: recurso de outro usuário responde `404`, igual a um recurso inexistente.

## API

Documentação interativa (Swagger) em **`/docs`** com a API rodando. Listagens aceitam `limit` (até 1000, padrão 100) e `offset`. Datas sem fuso são tratadas como UTC.

| Grupo | Rotas principais |
| ----- | ---------------- |
| **Auth** | `POST /auth/login`, `/auth/ativar-conta`, `/auth/2fa/verify`, `/auth/2fa/reenviar`, `/auth/refresh`, `/auth/logout`, `GET /auth/me`, `POST /auth/trocar-senha`, `/auth/esqueci-senha`, `/auth/redefinir-senha` |
| **2FA TOTP** | `GET /auth/2fa/totp/status`, `POST /iniciar` (QR code), `/confirmar`, `/recuperacao/regenerar`, `/desativar` |
| **Usuários e perfis** | `/usuarios`, `/perfis` |
| **Sensores e leituras** | `/sensores`, `/sensores/{id}/leituras`, `/leituras`, `/leituras/ultima`, `/leituras/estatisticas`, `/leituras-rejeitadas` |
| **Lotes e catálogo** | `/lotes`, `/frutas`, `/config-parametros`, `/catalogo/*` (propriedades, safras, variedades, portos, perdas de risco) |
| **Alertas** | `/alertas`, `/alertas-preditivos`, `/central-alertas` (+ `/exportar.csv`, `/curva`) |
| **Previsões e risco** | `/previsoes/janela-colheita`, `/previsoes/risco-climatico/gerar`, `/previsoes/prejuizo/gerar`, `/previsoes/irrigacao`, `/riscos/prejuizo`, `/riscos/climatico`, `/clima/previsao` |
| **IA** | `GET /ia/parecer`, `/ia/modelos`, `/recomendacoes`, `/pareceres` (gerar, editar, assinar) |
| **Dashboard** | `/dashboard/resumo`, `POST /dashboard/stream/ticket` + `GET /dashboard/stream` (SSE), `/analista/*` |
| **Relatórios** | `/relatorios`, `/relatorios/{id}/csv`, `/relatorios/{id}/enviar-email`, `/relatorios/saidas-faixa` |
| **Operação** | `/calibracao/*`, `/notificacoes/*`, `/preferencias/*`, `/dados-mercado`, `/auditoria` |

> Para testar rápido, importe `qa-api/raiz.postman_collection.json` e `qa-api/raiz.postman_environment.json` no Postman.

## Ingestão de dados

O serviço consulta a última leitura do canal a cada `POLL_INTERVAL_SECONDS` (padrão 20 s). Para cada leitura nova:

1. **Valida** (`src/validacao.py`): `entry_id` inteiro, data ISO 8601, valores numéricos, finitos e dentro das faixas configuradas.
2. **Grava** em `leitura_climatica` se válida (deduplicação por `ON CONFLICT (sensor, entry_id_thingspeak)`).
3. **Rejeita** se inválida: guarda valores brutos e motivo em `leitura_rejeitada`.

Por padrão: `field1` = temperatura, `field2` = umidade do ar, `field3` = umidade do solo. Tudo é ajustável via `TS_FIELD_*`.

> Um serviço de ingestão atende **um canal e um sensor** (`SENSOR_ID`).

## Agendador

Rodando dentro do `python -m src.main`, o agendador executa tarefas em segundo plano, sem travar a coleta:

| Tarefa | Intervalo padrão |
| ------ | :--------------: |
| Risco climático | 180 min |
| Alertas preditivos | 180 min |
| Janela de colheita | 360 min |
| Irrigação | 360 min |
| Prejuízo | 360 min |
| Parecer de IA (só chama a IA quando o parecer do lote venceu) | 15 min |

Falhas são registradas no log e tentadas de novo depois (`AGENDADOR_RETRY_MIN`). Para desligar tudo: `AGENDADOR_ATIVO=false`.

## Como executar

### Pré-requisitos

- Python 3.11+
- PostgreSQL com o banco já preparado (veja [Banco de dados](#-banco-de-dados))
- Canal no ThingSpeak (ou use o `seed_demo` para dados de demonstração)
- Chave da API do Gemini/groq (opcional, só para os recursos de IA)

### 1. Clonar e instalar

```bash
git clone https://github.com/rafaellins7/iot-backend-.git
cd iot-backend-

python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 2. Configurar o `.env`

```bash
cp .env.example .env
```

Gere as chaves de segurança:

```bash
# Chave Fernet que cifra o segredo TOTP
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Variáveis principais (a lista completa e comentada está no `.env.example`):

| Grupo | Variáveis |
| ----- | --------- |
| **ThingSpeak** | `THINGSPEAK_CHANNEL_ID`, `THINGSPEAK_READ_API_KEY` (canal privado), `POLL_INTERVAL_SECONDS`, `SENSOR_ID`, `TS_FIELD_*` |
| **Banco** | `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` |
| **Segurança** | `JWT_SECRET`, `EMAIL_OTP_KEY`, `TOTP_ENC_KEY`, `LOGIN_2FA_EMAIL`, `MISSION_CODE` |
| **E-mail** | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_MODO_DEV` |
| **IA** | `GEMINI_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_MODELOS_RESERVA`, `PARECER_TTL_MIN` |
| **Clima** | `CLIMA_LATITUDE`, `CLIMA_LONGITUDE`, `CLIMA_TIMEZONE`, `CLIMA_CACHE_SEGUNDOS` |
| **Validação** | `TEMP_MIN_VALIDA`, `TEMP_MAX_VALIDA`, `UMIDADE_MIN_VALIDA`, `UMIDADE_MAX_VALIDA` |
| **Agendador e notificações** | `AGENDADOR_*`, `NOTIFICACAO_*` |
| **Web** | `CORS_ORIGINS` |

> Em desenvolvimento, use `EMAIL_MODO_DEV=true` para não enviar e-mails de verdade.

### 3. Subir os serviços

```bash
# Coleta + agendador (em um terminal)
python -m src.main

# API (em outro terminal)
uvicorn src.api.app:app --reload
```

API em `http://127.0.0.1:8000` e documentação em `/docs`.

### 4. Utilitários

```bash
python -m scripts.backfill_historico   # importa as últimas 100 leituras do canal
python -m scripts.seed_demo            # dados de demonstração (precisa da API rodando e de um Administrador)
python test_gemini.py                  # confere se a chave do Gemini está funcionando
```

## Banco de dados

O banco fica em outro repositório: **[LorenaLira05/iot_db](https://github.com/LorenaLira05/iot_db)**. Este backend **não cria nem altera o esquema**: ele se conecta a um banco já preparado.

Rode os scripts de lá na ordem: `schema.sql`, `restricoes.sql`, `seed.sql`, `triggers.sql`, `views.sql` (mais `auth.sql` e `implementação_ia.sql` para autenticação e previsões). Para as tabelas do 2FA TOTP, use também o `totp.sql` descrito em [`seguranca/README.md`](seguranca/README.md). Para o parecer de IA, existe a migração `scripts/migracao_parecer_geracao.sql` (aplicável com `python -m scripts.aplicar_migracao_parecer`).

## Testes

```bash
pytest
```

- Os testes usam o banco definido em `TEST_DB_NAME` (padrão `raiz_teste`), para não sujar o banco principal.
- Testes de integração precisam das variáveis `DB_*` configuradas.
- Cobertura por área: IDOR e escopo, permissões por perfil, TOTP (unidade e integração), senha, agendador, alertas, cálculos de previsão, pareceres e stream.

## Segurança

A pasta [`seguranca/`](seguranca/) documenta os controles implementados no Projeto Integrador, com evidências de "antes e depois":

| Controle | Ameaça | Como funciona |
| -------- | ------ | ------------- |
| **2FA por TOTP** | Senha vazada | RFC 6238, segredo cifrado com Fernet, códigos de recuperação de uso único, passo já usado não vale de novo, bloqueio após 5 falhas em 15 min |
| **Proteção contra IDOR/BOLA** | Produtor trocando IDs na URL para ver dados de outro | Verificação de dono no servidor (`src/api/escopo.py`) usando o usuário do token; recurso alheio responde `404` |

Outros pontos: senhas com **argon2id**, JWT de acesso curto (15 min) com refresh de 7 dias, consulta do usuário a cada requisição (desativar vale na hora), SQL parametrizado, CORS restrito, auditoria em `log_acesso` e log de bloqueios em `seguranca.log`.

Veja também o [modelo de ameaças](seguranca/modelo-ameacas.md), o [uso de IA no projeto](seguranca/uso-de-ia.md) e as evidências em `seguranca/evidencias/`.

## Estrutura

```text
iot-backend/
├── src/
│   ├── api/
│   │   ├── routers/            # um arquivo por recurso
│   │   ├── services/           # IA (llm_client, pareceres), notificações, ativação
│   │   ├── app.py              # FastAPI, CORS, perfis e registro dos routers
│   │   ├── deps_auth.py        # usuário atual e controle por perfil
│   │   ├── escopo.py           # proteção contra IDOR (escopo por dono)
│   │   ├── security_auth.py    # JWT e hash de senha
│   │   ├── totp.py / totp_db.py
│   │   ├── auditoria.py        # registro em log_acesso
│   │   └── schemas.py          # modelos Pydantic
│   ├── tests/                  # suíte pytest
│   ├── agendador.py            # tarefas preditivas em segundo plano
│   ├── main.py                 # loop de ingestão
│   ├── database.py             # conexão e gravação das leituras
│   ├── thingspeak_client.py
│   ├── open_meteo_client.py
│   └── validacao.py
├── scripts/                    # backfill, seed de demo, migrações
├── seguranca/                  # controles, ameaças, testes e evidências
├── qa-api/                     # coleção e ambiente do Postman
├── .env.example
└── requirements.txt
```

## 🗺️ Roadmap

- [x] API FastAPI organizada por routers
- [x] Ingestão com validação, deduplicação e leituras rejeitadas
- [x] Autenticação (JWT), 2FA por TOTP e e-mail, recuperação de senha
- [x] Controle de acesso por perfil (RBAC) e proteção contra IDOR
- [x] Alertas de faixa, alertas preditivos e central de alertas
- [x] Pareceres de IA (Gemini) e previsões (colheita, risco, prejuízo, irrigação)
- [x] Agendador em segundo plano
- [x] Notificações por e-mail
- [x] Stream em tempo real (SSE)
- [x] Testes automatizados
- [x] Deploy
- [ ] Ingestão de vários sensores/canais
- [ ] Rate limit por IP no `/auth/2fa/verify`
- [ ] Cadastro de TOTP obrigatório no primeiro login

## Equipe

Projeto Integrador, Análise e Desenvolvimento de Sistemas, Faculdade Senac Pernambuco.

Lorena Lira · Maria Clara · Luiz Felipe · Victor Daniel · Ruan Gualberto · Ricardo Rafael · Caio Barreto

## Créditos de dados

Previsão do tempo por [Open-Meteo](https://open-meteo.com/). Ao exibi-la na interface, cite a fonte (termos em <https://open-meteo.com/en/features#terms>).

## 📄 Licença

Projeto acadêmico.
