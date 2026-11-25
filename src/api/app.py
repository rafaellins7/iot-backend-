import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import config
from src.api.deps_auth import (ADMIN, ANALISTA, PRODUTOR_EXPORTADOR, get_current_user, require_role,
                               require_role_por_metodo)
from src.api.routers import (alertas, alertas_preditivos, analista, central_alertas, auditoria, auth,
                             catalogo, clima, config_parametros, dados_mercado,
                             dashboard, frutas, ia, leituras, leituras_rejeitadas, lotes,
                             perfis, previsoes, previsoes_ia, recomendacoes, relatorios,
                             relatorios_gerados, risco, sensor_leituras, sensores,
                             usuarios, pareceres, notificacoes, parecer_ia, dashboard_stream, calibracao, totp, preferencias)

# O Administrador passa em TODAS as regras (bypass em deps_auth), então não é listado aqui.
# O Produtor/Exportador é somente leitura: nenhuma regra lhe dá POST/PUT/PATCH/DELETE.

# só Administrador
admin = [Depends(require_role(ADMIN))]

# Analista e Produtor consultam (GET); só o Admin escreve.
# O parecer automático de IA (GET /ia/parecer) fica aqui: os 3 perfis só leem, ninguém gera.
consulta = [Depends(require_role_por_metodo(
    leitura=(ANALISTA, PRODUTOR_EXPORTADOR), escrita=()))]

# Analista consulta e edita (sem excluir); Produtor só consulta; Admin faz tudo
analista_edita = [Depends(require_role_por_metodo(
    leitura=(ANALISTA, PRODUTOR_EXPORTADOR), escrita=(ANALISTA,), exclusao=()))]

# Analista e Produtor consultam e geram pareceres; Admin faz tudo
parecer_acesso = [Depends(require_role_por_metodo(
    leitura=(ANALISTA, PRODUTOR_EXPORTADOR), escrita=(ANALISTA, PRODUTOR_EXPORTADOR), exclusao=()))]

# Analista consulta e gera (sem excluir); Produtor fora; Admin faz tudo
analista_so_ae = [Depends(require_role_por_metodo(
    leitura=(ANALISTA,), escrita=(ANALISTA,), exclusao=()))]

# Só Analista consulta (Produtor fora); Admin faz tudo.
# Telas e relatórios que agregam dados de TODOS os donos: o Produtor não tem escopo para eles.
so_analista = [Depends(require_role_por_metodo(
    leitura=(ANALISTA,), escrita=()))]

# Só Produtor consulta (Analista fora); Admin faz tudo
so_produtor = [Depends(require_role_por_metodo(
    leitura=(PRODUTOR_EXPORTADOR,), escrita=()))]


@asynccontextmanager
async def lifespan(app: FastAPI):
    coleta_ativa = (
        os.getenv("COLETA_AUTOMATICA", "true").lower() == "true"
        and "PYTEST_CURRENT_TEST" not in os.environ
    )
    if coleta_ativa:
        try:
            from src import agendador, database, thingspeak_client
            agendador.iniciar_em_segundo_plano()

            def _loop_coleta():
                ultimo_entry_id = None
                while True:
                    try:
                        leitura = thingspeak_client.buscar_ultima_leitura()
                        if leitura and leitura.get("entry_id") != ultimo_entry_id:
                            database.processar_leitura(leitura)
                            ultimo_entry_id = leitura["entry_id"]
                    except Exception:
                        pass
                    time.sleep(config.POLL_INTERVAL_SECONDS)

            t = threading.Thread(target=_loop_coleta, daemon=True, name="ColetaThingSpeak")
            t.start()
        except Exception:
            pass
    yield


app = FastAPI(title="API - Dashboard Climático e Logístico", lifespan=lifespan)

@app.get("/", include_in_schema=False)
def raiz():
    return {"status": "ok", "docs": "/docs"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# público (login, refresh, 2FA) — /auth/me exige token
app.include_router(auth.router)
app.include_router(totp.router)   # cadastro/gestão do 2º fator TOTP (exige login)
app.include_router(notificacoes.router)
app.include_router(preferencias.router)
app.include_router(dashboard_stream.router)  # SSE: o GET usa ticket de uso único (POST /dashboard/stream/ticket exige login)

for r in (perfis, usuarios):
    app.include_router(r.router, dependencies=admin)

for r in (leituras, leituras_rejeitadas, sensor_leituras, dashboard, clima, lotes, frutas,
          risco, previsoes, parecer_ia):
    app.include_router(r.router, dependencies=consulta)

# resumos agregados (sem filtro por dono): só Analista/Admin
app.include_router(analista.router, dependencies=so_analista)
app.include_router(calibracao.router, dependencies=analista_edita)

for r in (sensores, config_parametros, alertas, alertas_preditivos, catalogo,
          relatorios, central_alertas):
    app.include_router(r.router, dependencies=analista_edita)

app.include_router(pareceres.router, dependencies=parecer_acesso)

# relatórios gerados/exportados cobrem todos os donos: Analista consulta e gera; Produtor fora
app.include_router(relatorios_gerados.router, dependencies=analista_so_ae)

for r in (dados_mercado, ia, recomendacoes, previsoes_ia):
    app.include_router(r.router, dependencies=so_produtor)

# log de acesso (IPs, ações de todos os usuários): só Administrador
app.include_router(auditoria.router, dependencies=admin)