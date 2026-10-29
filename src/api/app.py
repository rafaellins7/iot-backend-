from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import config
from src.api.deps_auth import ADMIN, PRODUTOR_EXPORTADOR, require_role
from src.api.routers import (alertas, alertas_preditivos, auditoria, auth, clima,
                             config_parametros, dados_mercado, dashboard, frutas, ia,
                             leituras, leituras_rejeitadas, lotes, perfis, previsoes,
                             previsoes_ia, recomendacoes, relatorios, relatorios_gerados,
                             risco, sensor_leituras, sensores, usuarios, viagens)

admin = [Depends(require_role(ADMIN))]
produtor = [Depends(require_role(PRODUTOR_EXPORTADOR, ADMIN))]  # já inclui o Admin

app = FastAPI(title="API - Dashboard Climático e Logístico")

@app.get("/", include_in_schema=False)
def raiz():
    return {"status": "ok", "docs": "/docs"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# público (login, refresh, 2FA)
app.include_router(auth.router)

# só Administrador
for r in (perfis, usuarios):
    app.include_router(r.router, dependencies=admin)

# Produtor/Exportador (e Admin)
for r in (leituras, leituras_rejeitadas, auditoria, clima, sensores, config_parametros,
          dashboard, sensor_leituras, lotes, alertas, frutas, dados_mercado,
          relatorios, relatorios_gerados, viagens, risco,
          previsoes, alertas_preditivos, ia, recomendacoes, previsoes_ia):
    app.include_router(r.router, dependencies=produtor)