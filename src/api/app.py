from fastapi import FastAPI

from src.api.routers import auditoria, leituras, leituras_rejeitadas, perfis, usuarios

app = FastAPI(title="API - Dashboard Climático e Logístico")

app.include_router(perfis.router)
app.include_router(usuarios.router)
app.include_router(leituras.router)
app.include_router(leituras_rejeitadas.router)
app.include_router(auditoria.router)