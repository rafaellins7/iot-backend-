import os

# Valores falsos, só para os testes. NÃO são usados na API real.
os.environ.setdefault("JWT_SECRET", "segredo-de-teste-nao-usar-em-producao")
os.environ.setdefault("EMAIL_OTP_KEY", "chave-de-teste-nao-usar-em-producao")
# Chave Fernet FALSA de teste (não usar fora dos testes)
os.environ.setdefault("TOTP_ENC_KEY", "Y2hhdmUtZGUtdGVzdGUtMzItYnl0ZXMtZXhhdG9zISE=")
os.environ.setdefault("MISSION_CODE", "TESTE1")
os.environ.setdefault("SEGURANCA_LOG_FILE", os.devnull)
