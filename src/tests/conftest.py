import os
import pytest

# Banco e credenciais para os testes (evita sujar o banco de produção 'raiz')
os.environ.setdefault("DB_NAME", os.getenv("TEST_DB_NAME", "raiz_teste"))
os.environ.setdefault("JWT_SECRET", "segredo-de-teste-nao-usar-em-producao")
os.environ.setdefault("EMAIL_OTP_KEY", "chave-de-teste-nao-usar-em-producao")
os.environ.setdefault("TOTP_ENC_KEY", "Y2hhdmUtZGUtdGVzdGUtMzItYnl0ZXMtZXhhdG9zISE=")
os.environ.setdefault("MISSION_CODE", "TESTE1")
os.environ.setdefault("SEGURANCA_LOG_FILE", os.devnull)

@pytest.fixture(autouse=True)
def limpar_sensores_teste():
    """Garante que nenhum sensor com prefixo de teste permaneça gravado após a execução dos testes."""
    yield
    try:
        from src.database import conectar
        with conectar() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sensor WHERE nome ILIKE '%TESTE IDOR%' OR nome ILIKE 'Sensor Teste%'")
            conn.commit()
    except Exception:
        pass

