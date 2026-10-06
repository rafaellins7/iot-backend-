import os
from dotenv import load_dotenv

load_dotenv()

THINGSPEAK_CHANNEL_ID = os.getenv("THINGSPEAK_CHANNEL_ID", "")
THINGSPEAK_READ_API_KEY = os.getenv("THINGSPEAK_READ_API_KEY", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "20"))

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

# Origens liberadas no CORS (o Vite muda de porta: 5173 e 5174)
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174",
).split(",") if o.strip()]

# Valores fora delas vão para o log de leituras rejeitadas 
TEMP_MIN_VALIDA = float(os.getenv("TEMP_MIN_VALIDA", "-40"))
TEMP_MAX_VALIDA = float(os.getenv("TEMP_MAX_VALIDA", "80"))
UMIDADE_MIN_VALIDA = float(os.getenv("UMIDADE_MIN_VALIDA", "0"))
UMIDADE_MAX_VALIDA = float(os.getenv("UMIDADE_MAX_VALIDA", "100")) 
