from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import config
from src.api.routers import auditoria, clima, config_parametros, leituras, leituras_rejeitadas, perfis, sensores, usuarios, dashboard, sensor_leituras

app = FastAPI(title="API - Dashboard Climático e Logístico")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(perfis.router)
app.include_router(usuarios.router)
app.include_router(leituras.router)
app.include_router(leituras_rejeitadas.router)
app.include_router(auditoria.router)
app.include_router(clima.router)
app.include_router(sensores.router)
app.include_router(config_parametros.router)
app.include_router(dashboard.router)
app.include_router(sensor_leituras.router)