import asyncio
import json
import secrets
import threading
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from src import database
from src.api.deps_auth import ANALISTA, PRODUTOR_EXPORTADOR, require_role

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

INTERVALO_S = 5                        # frequência de checagem/envio
HEARTBEAT_S = 15                       # comentário SSE para manter a conexão viva
LEITURA_VELHA = timedelta(minutes=10)  # acima disso, considera o sensor offline

# --- Ticket de uso único -------------------------------------------------------
# O EventSource do navegador não envia o header Authorization. Então o front (já logado) pede um
# ticket curto em POST /dashboard/stream/ticket e abre o stream com ?ticket=... O ticket vale
# poucos segundos e só uma vez, por isso não precisa pôr o JWT na URL.
# Guardado em memória: com vários workers/processos, use Redis (ou fixe 1 worker).
TICKET_VALIDADE_S = 30
MAX_CONEXOES = 50            # conexões SSE simultâneas (protege o servidor)

_tickets: dict[str, tuple[float, int]] = {}   # ticket -> (expira_em, id_usuario)
_tickets_lock = threading.Lock()
_conexoes = 0


def emitir_ticket(id_usuario: int) -> str:
    agora = time.monotonic()
    ticket = secrets.token_urlsafe(32)
    with _tickets_lock:
        for t in [t for t, (exp, _) in _tickets.items() if exp < agora]:   # limpa vencidos
            del _tickets[t]
        _tickets[ticket] = (agora + TICKET_VALIDADE_S, id_usuario)
    return ticket


def consumir_ticket(ticket: str) -> bool:
    """True se o ticket existe e não venceu. Sempre o remove (uso único)."""
    with _tickets_lock:
        dados = _tickets.pop(ticket, None)
    return dados is not None and dados[0] >= time.monotonic()


def buscar_ultima_leitura():
    """Última leitura real (ThingSpeak) com temperatura e umidade preenchidas."""
    conn = database.conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.temperatura, l.umidade, l.data_hora, s.nome
                FROM leitura_climatica l
                JOIN sensor s ON s.id_sensor = l.fk_sensor_id_sensor
                WHERE lower(l.origem) = 'thingspeak'
                  AND l.temperatura IS NOT NULL AND l.umidade IS NOT NULL
                ORDER BY l.data_hora DESC, l.id_leitura DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "temperatura": float(row[0]),
        "umidade": float(row[1]),
        "data_hora": row[2],
        "sensor": row[3],
    }


def montar_payload():
    """Retorna a última leitura real do banco COM a data dela, ou status 'sem_dados'. NUNCA simula."""
    agora = datetime.now(timezone.utc)
    real = None
    try:
        real = buscar_ultima_leitura()
    except Exception:
        real = None  # banco indisponível: não derruba o stream

    if real:
        dh = real["data_hora"]
        if dh.tzinfo is None:
            dh = dh.replace(tzinfo=timezone.utc)
        recente = (agora - dh <= LEITURA_VELHA)
        return {
            "temperatura": real["temperatura"],
            "umidade": real["umidade"],
            "origem": "real",
            "timestamp": dh.isoformat(),
            "sensor": real.get("sensor") or "DHT11 ESP32-C3",
            "status": "online" if recente else "offline",
            "recente": recente,
        }

    return {
        "status": "sem_dados",
        "origem": "sem_dados",
        "temperatura": None,
        "umidade": None,
        "timestamp": None,
        "sensor": None,
        "recente": False,
    }


async def gerador_leituras(request: Request):
    """Fluxo SSE contínuo. Encerra quando o cliente desconecta."""
    global _conexoes
    _conexoes += 1
    try:
        async for msg in _fluxo(request):
            yield msg
    finally:
        _conexoes -= 1


async def _fluxo(request: Request):
    loop = asyncio.get_event_loop()
    ultima_msg = loop.time()
    ultimo_envio = None

    while True:
        if await request.is_disconnected():
            break

        payload = await run_in_threadpool(montar_payload)

        # Envia apenas quando o payload mudar ou no heartbeat
        chave = (payload.get("status"), payload.get("origem"), payload.get("timestamp"))
        if chave != ultimo_envio:
            yield f"data: {json.dumps(payload)}\n\n"
            ultimo_envio = chave
            ultima_msg = loop.time()
        elif loop.time() - ultima_msg >= HEARTBEAT_S:
            yield ": keep-alive\n\n"  # comentário SSE, o front ignora
            ultima_msg = loop.time()

        await asyncio.sleep(INTERVALO_S)


@router.post("/stream/ticket")
def pedir_ticket_stream(user=Depends(require_role(ANALISTA, PRODUTOR_EXPORTADOR))):
    """Exige login (Bearer). Devolve um ticket de uso único para abrir o stream."""
    return {"ticket": emitir_ticket(user["id_usuario"]), "expira_em_s": TICKET_VALIDADE_S}


@router.get("/stream")
async def stream_telemetria_ao_vivo(request: Request, ticket: str = Query(..., min_length=20, max_length=200)):
    """Endpoint SSE (Server-Sent Events) para o dashboard em tempo real. Exige ?ticket=."""
    if not consumir_ticket(ticket):
        raise HTTPException(status_code=401, detail="Ticket inválido ou expirado")
    if _conexoes >= MAX_CONEXOES:
        raise HTTPException(status_code=503, detail="Muitas conexões no stream. Tente novamente em instantes")
    return StreamingResponse(
        gerador_leituras(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  
        },
    )