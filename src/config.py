import os
from dotenv import load_dotenv

load_dotenv()

THINGSPEAK_CHANNEL_ID = os.getenv("THINGSPEAK_CHANNEL_ID", "")
THINGSPEAK_READ_API_KEY = os.getenv("THINGSPEAK_READ_API_KEY", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "20"))

DATABASE_URL = os.getenv("DATABASE_URL")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
SENSOR_ID = int(os.getenv("SENSOR_ID", "1"))

# Open-Meteo 
CLIMA_LATITUDE = os.getenv("CLIMA_LATITUDE")
CLIMA_LONGITUDE = os.getenv("CLIMA_LONGITUDE")
CLIMA_TIMEZONE = os.getenv("CLIMA_TIMEZONE", "America/Recife")
CLIMA_CACHE_SEGUNDOS = int(os.getenv("CLIMA_CACHE_SEGUNDOS", "600"))

# Origens liberadas no CORS (o Vite muda de porta: 5173 e 5174, e deploy na Vercel)
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174,https://raiz-agro-iot.vercel.app",
).split(",") if o.strip()]

# Valores fora delas vão para o log de leituras rejeitadas 
TEMP_MIN_VALIDA = float(os.getenv("TEMP_MIN_VALIDA", "-40"))
TEMP_MAX_VALIDA = float(os.getenv("TEMP_MAX_VALIDA", "80"))
UMIDADE_MIN_VALIDA = float(os.getenv("UMIDADE_MIN_VALIDA", "0"))
UMIDADE_MAX_VALIDA = float(os.getenv("UMIDADE_MAX_VALIDA", "100")) 

SOLO_RAW_SECO = float(os.getenv("SOLO_RAW_SECO", "960"))
SOLO_RAW_MOLHADO = float(os.getenv("SOLO_RAW_MOLHADO", "800"))
SOLO_RAW_TOLERANCIA = float(os.getenv("SOLO_RAW_TOLERANCIA", "60"))

# Número do field do ThingSpeak em que cada medida chega. Os de solo são opcionais: vazio = não coleta.
def _campo_opcional(nome):
    valor = os.getenv(nome, "").strip()
    return int(valor) if valor.isdigit() else None


TS_FIELD_TEMPERATURA = int(os.getenv("TS_FIELD_TEMPERATURA", "1"))
TS_FIELD_UMIDADE = int(os.getenv("TS_FIELD_UMIDADE", "2"))
TS_FIELD_UMIDADE_SOLO = _campo_opcional("TS_FIELD_UMIDADE_SOLO")
TS_FIELD_TEMPERATURA_SOLO = _campo_opcional("TS_FIELD_TEMPERATURA_SOLO")

NOTIFICACAO_ATIVA = os.getenv("NOTIFICACAO_ATIVA", "false").lower() == "true"
NOTIFICACAO_INTERVALO_MIN = int(os.getenv("NOTIFICACAO_INTERVALO_MIN", "60"))
NOTIFICACAO_JANELA_HORAS = int(os.getenv("NOTIFICACAO_JANELA_HORAS", "24"))
NOTIFICACAO_MAX_TENTATIVAS = int(os.getenv("NOTIFICACAO_MAX_TENTATIVAS", "3"))
NOTIFICACAO_RETRY_MIN = int(os.getenv("NOTIFICACAO_RETRY_MIN", "5"))
NOTIFICACAO_PERFIS = [p.strip().lower() for p in os.getenv("NOTIFICACAO_PERFIS", "").split(",") if p.strip()]
ATIVACAO_VALIDADE_H = int(os.getenv("ATIVACAO_VALIDADE_H", "72"))
TERMOS_VERSAO = os.getenv("TERMOS_VERSAO", "1.0")

ESP32_INTERVALO_ENVIO_S = int(os.getenv("ESP32_INTERVALO_ENVIO_S", "20"))