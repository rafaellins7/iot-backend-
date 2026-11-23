# Modelo de ameaças — Raiz (Dashboard Climático e Logístico)

Escopo: API FastAPI + PostgreSQL + dashboard React; sensor DHT11/ESP32 → ThingSpeak → ingestão. Método: STRIDE resumido.

| # | Ameaça (STRIDE) | Impacto no projeto | Tratada por | Situação |
|---|---|---|---|---|
| 1 | **Spoofing** — senha vazada/adivinhada e login por terceiro | Acesso a lotes, alertas, pareceres e relatórios de exportação de outra fazenda | **OTP (TOTP)** + bloqueio após 5 falhas + hash argon2 | Tratada; risco residual se o celular for roubado/desbloqueado |
| 2 | **Information disclosure / Tampering (IDOR/BOLA)** — produtor troca o ID na URL e lê/altera sensor, leitura ou lote de outro | Vazamento de dados de safra (concorrência), alteração de faixas/alertas que levam a prejuízo de carga | **Verificação de dono** no servidor (`src/api/escopo.py`), 404 para recurso alheio | Tratada para o perfil Produtor; Analista e Admin têm escopo total por regra de negócio |
| 3 | **Tampering** — dados falsos no canal ThingSpeak (chave de escrita vazada) | Leituras falsas disparam ou escondem alertas | — | **Aberta.** Mitigação parcial: validação de faixa na ingestão e leitura rejeitada |
| 4 | **Repudiation / abuso interno** — Admin/Analista acessam tudo | Uso indevido sem dono responsável | — | **Aberta.** Mitigação parcial: trilha em `log_acesso` |
| 5 | **Info disclosure** — .env, chaves de API e SMTP no repositório | Tomada de contas de e-mail e de IA | `.gitignore`, `.env.example` | Parcial: conferir histórico do Git (ver README) |

Prioridade: 1 e 2 primeiro porque dão acesso direto a dados de negócio de outros clientes com esforço mínimo (uma senha vazada ou editar um número na URL); 3 exige acesso ao canal e 4 exige conta privilegiada.
