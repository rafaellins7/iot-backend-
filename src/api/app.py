from fastapi import FastAPI

from src.api.routers import perfis, usuarios

app = FastAPI(title="API - Dashboard Climático e Logístico")

app.include_router(perfis.router)
app.include_router(usuarios.router)