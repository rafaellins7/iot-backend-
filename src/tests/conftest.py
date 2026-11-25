import os

# A API não pode coletar do ThingSpeak (rede) durante os testes.
os.environ["COLETA_AUTOMATICA"] = "false"

# Valores falsos, só para os testes. NÃO são usados na API real.
os.environ.setdefault("JWT_SECRET", "segredo-de-teste-nao-usar-em-producao")
os.environ.setdefault("EMAIL_OTP_KEY", "chave-de-teste-nao-usar-em-producao")