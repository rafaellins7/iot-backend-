# Segurança no Projeto Integrador — Raiz

## 1. Identificação
- Integrantes: <NOME — @usuario-github> · <NOME — @usuario-github> · <NOME — @usuario-github>
- Projeto do PI: Dashboard de Monitoramento Climático e Logístico em Nuvem para Exportadoras de Frutas (Raiz)
- Código de missão: **<CÓDIGO>**

## 2. O projeto
Sensor DHT11 + ESP32-C3 publica no ThingSpeak; o serviço de ingestão (`python -m src.main`) valida e grava no PostgreSQL; a API FastAPI (`uvicorn src.api.app:app`) serve o dashboard React. Perfis: Produtor/Exportador, Analista de Dados, Administrador. Dispositivo = **sensor** (`sensor.fk_usuario_id_usuario` é o dono).

## Preparação (uma vez)
```bash
pip install -r requirements.txt
psql ... -f seguranca/sql/totp.sql                      # tabelas do TOTP (depois de auth.sql do repo iot_db)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # -> TOTP_ENC_KEY no .env
# .env: TOTP_ENC_KEY=..., MISSION_CODE=<CÓDIGO>, JWT_SECRET, EMAIL_OTP_KEY, DB_*
uvicorn src.api.app:app --port 8000
```
Dados de teste: 2 usuários Produtor/Exportador, cada um com um lote e um sensor (`fk_usuario_id_usuario` preenchido).

---
## 3–7. Controle 1 — Autenticação em dois fatores (TOTP)

**3. A ameaça.** Senha vazada permite entrar na conta e ver/alterar lotes e relatórios. Impacto: vazamento comercial e dano a cargas.

**4. O controle.** Segundo fator por aplicativo autenticador (RFC 6238, 6 dígitos, 30 s).
- Cálculo/validação: [`src/api/totp.py`](../src/api/totp.py) — janela de ±1 passo, comparação em tempo constante.
- Banco: [`src/api/totp_db.py`](../src/api/totp_db.py) e [`seguranca/sql/totp.sql`](sql/totp.sql). Segredo **cifrado** (Fernet, `TOTP_ENC_KEY`); recuperação guarda só HMAC.
- Endpoints: [`src/api/routers/totp.py`](../src/api/routers/totp.py) (`/auth/2fa/totp/iniciar` devolve QR PNG, `/confirmar`, `/recuperacao/regenerar`, `/desativar`).
- Login: [`src/api/routers/auth.py`](../src/api/routers/auth.py) (`_continuar_login` e `/auth/2fa/verify`). A verificação é **no servidor**; o token temporário (`typ=2fa`) não abre nenhuma rota.
- Decisões: (a) passo já aceito não vale de novo (`ultimo_passo`, com `FOR UPDATE` contra corrida); (b) 10 códigos de recuperação de uso único, mostrados uma vez; (c) quem tem TOTP **nunca** cai no código por e-mail (evita rebaixar o fator); (d) falhas entram no bloqueio existente (5 em 15 min); (e) desativar exige senha + código.
- Log de bloqueio: `[<CÓDIGO>] BLOQUEIO OTP: ...` (console e `seguranca.log`).

**5. Como testar**
```bash
python seguranca/testes/otp_antes_depois.py --fase depois --email <email> --senha '<senha>' --id-usuario <id>
pytest src/tests/test_totp_unidade.py src/tests/test_totp_integracao.py   # integração precisa de DB_* no .env
```
**6. Resultado.** Antes: `seguranca/evidencias/otp_antes_<CÓDIGO>.txt` (feito no commit `<hash anterior>`). Depois: `otp_depois_<CÓDIGO>.txt` + vídeo `otp_depois_<CÓDIGO>.mp4` (≤90 s).
Contorno tentado: pedir código por e-mail no lugar do TOTP → 409; reuso de código → 401.

**7. Limitações.** Usuário que ainda não cadastrou TOTP continua no fluxo anterior (e-mail/sem 2º fator conforme `LOGIN_2FA_EMAIL`); próximo passo: tornar o cadastro obrigatório no primeiro login. Quem controla o e-mail ainda pode redefinir a senha, mas continua sem o TOTP. Sem rate limit por IP no `/2fa/verify` (só por usuário).

---
## 3–7. Controle 2 — Proteção contra IDOR

**3. A ameaça.** Produtor A troca o ID na requisição e lê, altera ou desativa sensor/leitura/lote do Produtor B.

**4. O controle.** Verificação de dono no servidor, com o usuário **do token** (nunca um ID enviado pelo cliente).
- [`src/api/escopo.py`](../src/api/escopo.py): `exigir_sensor`, `exigir_lote`, `filtrar_por_dono`, `filtrar_leituras_por_dono`; recurso alheio responde **404** igual a inexistente (não revela existência).
- Aplicado em sensores, leituras, leituras rejeitadas, lotes, alertas, relatórios, previsões (ver `grep -rn escopo src/api/routers`).
- Escrita (PUT/PATCH/DELETE) é negada ao Produtor por perfil (**403**) em [`src/api/app.py`](../src/api/app.py) / [`deps_auth.py`](../src/api/deps_auth.py).
- Log de bloqueio: `[<CÓDIGO>] BLOQUEIO IDOR: ...`.

**5. Como testar**
```bash
python seguranca/testes/idor_antes_depois.py --fase depois --usuario-a <idA> --sensor-a <sA> --usuario-b <idB> --sensor-b <sB> --lote-b <lB>
pytest src/tests/test_api_idor.py
```
**6. Resultado.** Antes: `idor_antes_<CÓDIGO>.txt` (commit anterior ao escopo por dono: tentativas passam). Depois: `idor_depois_<CÓDIGO>.txt` + vídeo. Contorno: IDs alterados em todas as rotas listadas, métodos de escrita e `id_sensor` em query string.

**7. Limitações.** Analista e Administrador têm escopo total por regra de negócio. Não há rota de "comando" ao dispositivo (o ESP32 só publica no ThingSpeak). O stream SSE (`/dashboard/stream`) é global do talhão A1, não por dono. Próximo passo: testes automatizados com banco real no pipeline.

## Como gerar o "antes" fiel
Rode os scripts num checkout do commit anterior a cada controle (`git worktree add ../antes <hash>`), com o mesmo `.env`. Não há flag para desligar controle no código.
