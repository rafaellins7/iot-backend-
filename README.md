# ValeSafra - Backend

Backend e serviço de ingestão IoT do **ValeSafra**, uma plataforma em desenvolvimento para monitoramento agrícola por meio de dados de sensores.

> **Projeto em desenvolvimento:** este backend está em fase inicial e ainda falta muita coisa a ser feita. Até agora existem apenas a coleta dos dados do ThingSpeak e os endpoints de usuários e perfis. Os demais endpoints, a autenticação completa, o controle de acesso e várias outras funcionalidades ainda serão desenvolvidos. Estrutura, regras de negócio e banco de dados podem mudar a qualquer momento. Este README reflete o estado atual do código e será atualizado conforme o projeto avançar.

## Sobre

O backend é responsável por:

* Integração com sensores **ESP32** através do **ThingSpeak**;
* Coleta de temperatura e umidade;
* Ingestão periódica dos dados (polling);
* Deduplicação das leituras;
* Comunicação com o PostgreSQL (o banco em si fica em outro repositório);
* Gerenciamento de usuários e perfis;
* Segurança das senhas com hash bcrypt.

## Fluxo

```text
ESP32 / DHT11
      |
  ThingSpeak
      |
 Serviço Python (polling)
      |
 PostgreSQL
      |
API / Dashboard
```

## Tecnologias

| Camada | Tecnologia |
| ------ | ---------- |
| API | Python, FastAPI, Uvicorn, Pydantic |
| Requisições e configuração | Requests, python-dotenv |
| Banco de dados | PostgreSQL, psycopg2-binary |
| Segurança | Passlib, bcrypt |
| IoT | ESP32, DHT11, ThingSpeak REST API |

## Estrutura

```text
iot-backend/
├── src/
│   ├── api/
│   │   ├── routers/
│   │   │   ├── perfis.py
│   │   │   └── usuarios.py
│   │   ├── app.py
│   │   ├── deps.py
│   │   ├── schemas.py
│   │   └── security.py
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   └── thingspeak_client.py
├── scripts/
│   └── backfill_historico.py
├── .env.example
├── requirements.txt
└── README.md
```

### Principais arquivos

| Arquivo/Pasta | Responsabilidade |
| ------------- | ---------------- |
| `src/main.py` | Loop de coleta: consulta o ThingSpeak e grava no banco |
| `src/thingspeak_client.py` | Comunicação com a API do ThingSpeak |
| `src/database.py` | Conexão e escrita no PostgreSQL |
| `src/config.py` | Leitura das variáveis de ambiente |
| `src/api/app.py` | Configuração da aplicação FastAPI |
| `src/api/routers/` | Endpoints separados por recurso |
| `src/api/deps.py` | Dependências dos endpoints (conexão por requisição) |
| `src/api/schemas.py` | Validação e estrutura dos dados da API |
| `src/api/security.py` | Hash e verificação de senhas |
| `scripts/backfill_historico.py` | Importa o histórico recente do canal de uma vez |

## Usuários e Perfis

O backend já possui endpoints de **usuários e perfis**, organizados por routers.

Os perfis previstos no sistema são:

* Administrador;
* Analista de Dados;
* Produtor / Exportador.

### Rotas atuais

| Método | Rota | Descrição |
| ------ | ---- | --------- |
| GET | `/perfis` | Listar perfis |
| GET | `/usuarios` | Listar usuários (filtro opcional `?status=ativo` ou `inativo`) |
| GET | `/usuarios/{id_usuario}` | Buscar usuário por ID |
| POST | `/usuarios` | Cadastrar usuário |
| PUT | `/usuarios/{id_usuario}` | Editar nome, e-mail, perfil ou status |
| DELETE | `/usuarios/{id_usuario}` | Desativar usuário (não apaga o registro) |
| PUT | `/usuarios/{id_usuario}/senha` | Trocar senha (exige a senha atual) |

A documentação interativa (Swagger) fica disponível em `/docs` com a API rodando.

### Endpoints previstos (ainda não implementados)

Os grupos abaixo fazem parte do escopo do projeto, mas **ainda não existem no código**. Nomes e rotas são preliminares e podem mudar.

| Grupo | O que deve cobrir |
| ----- | ----------------- |
| Autenticação | Login, logout, renovação de token e recuperação de senha |
| Sensores | Cadastro, listagem, edição e desativação de sensores |
| Leituras | Consulta de leituras por sensor e período, última leitura e estatísticas |
| Alertas | Regras de alerta, histórico e notificações |
| Dashboard | Dados agregados para gráficos e indicadores |
| Análises | Relatórios e exportação de dados |
| Predição | Consumo dos modelos preditivos |


## Autenticação e Segurança

Já implementado:

* Senhas armazenadas com hash bcrypt;
* Validação de e-mail e tamanho de senha (8 a 72 caracteres);
* Troca de senha com verificação da senha atual.

Ainda em desenvolvimento: login com token, controle de acesso por perfil e proteção dos endpoints. **No estado atual, as rotas da API não exigem autenticação.**

Informações sensíveis, como senhas e chaves de API, devem ficar em variáveis de ambiente e não devem ser versionadas.

## Banco de Dados

**O banco de dados deste projeto está em outro repositório**, separado deste backend:

* Repositório do banco: `<https://github.com/LorenaLira05/iot_db>`

Lá ficam a modelagem e os scripts SQL (tabelas, relacionamentos, constraints, triggers, views e dados iniciais). Este backend **não cria nem altera o banco**: ele apenas se conecta a um banco já preparado. Por isso, é preciso configurar o banco a partir daquele repositório antes de executar este projeto.

Tabelas utilizadas pelo código atual:

* `leitura_climatica`: leituras de temperatura e umidade dos sensores;
* `usuario`: usuários do sistema;
* `perfil`: perfis de acesso.

> A modelagem do banco também está em desenvolvimento e pode sofrer alterações. Se ela mudar, este backend precisará ser ajustado.

## Como Executar

### 1. Clonar o repositório

```bash
git clone https://github.com/rafaellins7/iot-backend-.git
cd iot-backend-
```

### 2. Criar ambiente virtual

```bash
python -m venv venv
```

Linux/Mac:

```bash
source venv/bin/activate
```

Windows:

```bash
venv\Scripts\activate
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Configurar o `.env`

Crie um arquivo `.env` baseado no `.env.example`:

### 5. Preparar o banco

O banco fica em um repositório separado (veja a seção [Banco de Dados](#banco-de-dados)). Clone-o, crie o banco e execute os scripts SQL de lá antes de continuar. Depois, use os dados de conexão no `.env`.

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

A API ficará disponível localmente em `http://127.0.0.1:8000`.

## Status do Projeto

### Implementado

* [x] Estrutura inicial da API com FastAPI
* [x] Integração com ThingSpeak
* [x] Coleta periódica dos dados
* [x] Importação de histórico
* [x] Persistência no PostgreSQL
* [x] Deduplicação das leituras
* [x] Endpoints de usuários
* [x] Endpoints de perfis
* [x] Schemas da API
* [x] Criptografia de senhas

### Em desenvolvimento / A fazer

* [ ] Login e autenticação com token
* [ ] Controle de acesso por perfil (RBAC)
* [ ] Proteção dos endpoints existentes
* [ ] Endpoints de sensores
* [ ] Endpoints de consulta das leituras
* [ ] Endpoints de dashboard e dados agregados
* [ ] Endpoints de análise e relatórios
* [ ] Sistema de alertas
* [ ] Modelos preditivos
* [ ] Integração com novos sensores
* [ ] Testes automatizados
* [ ] Tratamento de erros e logs mais completos
* [ ] Deploy

## Licença

Projeto acadêmico.
