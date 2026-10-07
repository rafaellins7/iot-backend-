from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import config
from src.api.routers import (alertas, auditoria, clima, config_parametros, dashboard,
                             leituras, leituras_rejeitadas, lotes, perfis, sensor_leituras, sensores, usuarios)

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
app.include_router(lotes.router)
app.include_router(alertas.router)