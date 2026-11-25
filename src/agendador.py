"""Gera automaticamente tudo o que é "preditivo" e alimenta o dashboard.

Sem esse mecanismo, os cards de janela de colheita, irrigação, risco, prejuízo, alertas preditivos e parecer de IA permanecem sem dados até que os respectivos endpoints POST `.../gerar` sejam acionados manualmente.

O arquivo `main.py` inicializa uma thread em segundo plano, responsável por executar periodicamente cada tarefa conforme seu respectivo intervalo de execução.

Dessa forma, operações com maior tempo de resposta, como consultas à Open-Meteo e processamento por IA, são executadas em segundo plano, sem bloquear ou atrasar o processo de coleta de dados do ThingSpeak.

As tarefas reaproveitam as funções dos próprios endpoints (mesmas regras, mesma auditoria em
log_acesso), sem passar por HTTP nem por login. Uma tarefa que falha é anotada no log e tentada de
novo mais tarde.

Variáveis do .env (todas opcionais; os intervalos são em minutos):
    AGENDADOR_ATIVO=true                  liga/desliga tudo
    AGENDADOR_EXECUTAR_NA_PARTIDA=true    roda tudo uma vez ao iniciar o main.py
    AGENDADOR_RISCO_MIN=180               risco climático
    AGENDADOR_JANELA_MIN=360              janela de colheita
    AGENDADOR_IRRIGACAO_MIN=360           irrigação
    AGENDADOR_PREJUIZO_MIN=360            prejuízo (usa o último risco climático)
    AGENDADOR_PREDITIVO_MIN=180           alertas preditivos (a partir do último risco climático)
    AGENDADOR_PARECER_MIN=15              parecer de IA: só chama a IA quando o parecer do lote venceu
    AGENDADOR_RETRY_MIN=15                espera depois de uma falha
    AGENDADOR_TICK_S=30                   de quanto em quanto tempo o segundo plano confere as tarefas
"""
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from src import config  # noqa: F401  (carrega o .env)


def _env_int(nome: str, padrao: int) -> int:
    try:
        return max(1, int(os.getenv(nome, str(padrao))))
    except ValueError:
        return padrao


def _env_bool(nome: str, padrao: bool) -> bool:
    return os.getenv(nome, str(padrao)).strip().lower() in ("1", "true", "sim", "yes")


class _Requisicao:
    """O 'auditar' dos endpoints só lê request.client (para o IP). Aqui não há cliente HTTP."""
    client = None


_REQ = _Requisicao()


def _usuario_sistema() -> dict:
    """Usuário "de sistema" para as funções de rota que exigem get_current_user.
    Perfil de administrador = escopo total (ver escopo.id_dono)."""
    from src.api.deps_auth import ADMIN
    return {
        "id_usuario": None,
        "nome": "agendador",
        "email": None,
        "ativo": True,
        "deve_trocar_senha": False,
        "perfil": ADMIN,
    }


def _cursor(conn):
    try:
        from psycopg2.extras import RealDictCursor
        return conn.cursor(cursor_factory=RealDictCursor)
    except ImportError:  # só acontece fora do projeto (testes sem psycopg2)
        return conn.cursor()


def _com_conexao(fn):
    from src import database
    conn = database.conectar()
    try:
        return fn(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _n(lista) -> str:
    return f"{len(lista)} registro(s)"


# ---------------------------------------------------------------- previsões que já existiam
def _janela_colheita() -> str:
    from src.api.routers import previsoes
    return _com_conexao(lambda c: _n(previsoes.gerar_janela_colheita(
        request=_REQ, id_lote=None, dias=7, conn=c)))


def _risco_climatico() -> str:
    from src.api.routers import previsoes
    return _com_conexao(lambda c: _n(previsoes.gerar_risco_climatico(
        request=_REQ, id_lote=None, dias=3, conn=c)))


def _irrigacao() -> str:
    from src.api.routers import previsoes_ia
    return _com_conexao(lambda c: _n(previsoes_ia.gerar_irrigacao(
        request=_REQ, id_lote=None, chuva_registrada_mm=0, incluir_nao_aprovados=False, conn=c)))


def _prejuizo() -> str:
    from src.api.routers import previsoes_ia
    return _com_conexao(lambda c: _n(previsoes_ia.gerar_prejuizo(
        request=_REQ, id_lote=None, nivel_risco=None, horas_fora_faixa=None, preco_kg=None,
        peso_caixa_kg=None, incluir_nao_aprovados=False, conn=c)))


# ---------------------------------------------------------------- alertas preditivos
MENSAGEM_MAX = 150  # limite prudente; aumente se a coluna alertas_preditivos.mensagem for maior


def escolher_corte(prob01: float, cortes: List[dict]) -> Optional[dict]:
    """Corte cuja faixa contém a probabilidade (0 a 1). Se cair numa fresta entre faixas, vale o
    maior corte cujo limiar_min já foi alcançado."""
    if not cortes:
        return None
    ordenados = sorted(cortes, key=lambda c: float(c["limiar_min"]))
    escolhido = None
    for c in ordenados:
        if float(c["limiar_min"]) <= prob01:
            escolhido = c
    return escolhido or ordenados[0]


def montar_mensagem(nivel_risco: Optional[str], acao: Optional[str]) -> str:
    texto = f"Risco climático {nivel_risco or 'indefinido'}: {acao or 'acompanhar a previsão'}"
    return texto if len(texto) <= MENSAGEM_MAX else texto[:MENSAGEM_MAX - 1].rstrip() + "…"


def gerar_alertas_preditivos(conn) -> str:
    """Um alerta preditivo por lote quando o último risco climático cai num corte acima de BAIXO.
    Não duplica: se já existe alerta EM ABERTO do mesmo lote e nível, não cria outro."""
    criados = ignorados = 0
    with _cursor(conn) as cur:
        cur.execute("SELECT nivel, limiar_min, limiar_max, acao_recomendada "
                    "FROM cortes_alerta_preditivo ORDER BY limiar_min")
        cortes = cur.fetchall()
        if not cortes:
            return "sem cortes cadastrados em cortes_alerta_preditivo"
        cur.execute(
            """SELECT DISTINCT ON (r.fk_lote_id_lote)
                      r.fk_lote_id_lote AS id_lote, r.nivel_risco, r.probabilidade, r.periodo_inicio
                 FROM risco_climatico r
                 JOIN lote l ON l.id_lote = r.fk_lote_id_lote
                WHERE lower(l.status::text) <> 'finalizado'
                ORDER BY r.fk_lote_id_lote, r.id_risco_climatico DESC""")
        riscos = cur.fetchall()
        for r in riscos:
            if r["probabilidade"] is None:
                continue
            # risco_climatico.probabilidade é um índice de 0 a 100; os cortes são de 0 a 1
            prob01 = min(1.0, max(0.0, float(r["probabilidade"]) / 100.0))
            corte = escolher_corte(prob01, cortes)
            if corte is None or str(corte["nivel"]).upper() == "BAIXO":
                continue
            cur.execute("""SELECT 1 FROM alertas_preditivos
                            WHERE id_lote = %s AND upper(status) = 'EM ABERTO'
                              AND upper(nivel_severidade) = upper(%s) LIMIT 1""",
                        (r["id_lote"], corte["nivel"]))
            if cur.fetchone():
                ignorados += 1
                continue
            cur.execute("SELECT id_sensor FROM sensor WHERE fk_lote_id_lote = %s ORDER BY id_sensor LIMIT 1",
                        (r["id_lote"],))
            sensor = cur.fetchone()
            cur.execute(
                """INSERT INTO alertas_preditivos (id_sensor, id_lote, probabilidade_risco,
                          nivel_severidade, mensagem, previsao_data_hora, status)
                   VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now() AT TIME ZONE 'UTC'), 'EM ABERTO')""",
                (sensor["id_sensor"] if sensor else None, r["id_lote"], round(prob01, 2),
                 corte["nivel"], montar_mensagem(r["nivel_risco"], corte["acao_recomendada"]),
                 r["periodo_inicio"]))
            criados += 1
    conn.commit()
    return f"{criados} criado(s), {ignorados} já em aberto, {len(riscos)} lote(s) avaliado(s)"


def _alertas_preditivos() -> str:
    return _com_conexao(gerar_alertas_preditivos)


# ---------------------------------------------------------------- parecer de IA
def pre_aquecer_pareceres(conn) -> str:
    """Pede o parecer de cada lote não finalizado. Processa sequencialmente com intervalo mínimo
    de PARECER_INTERVALO_S (padrão 6s) entre chamadas ao provedor."""
    from src.api import previsao_repo as repo
    from src.api.routers import parecer_ia
    with _cursor(conn) as cur:
        ids = [l["id_lote"] for l in repo.lotes_para_prejuizo(cur, None)]
    contagem = {"IA": 0, "FALLBACK_TEMPLATE": 0, "CACHE": 0, "SEM_DADOS": 0, "erro": 0}
    intervalo_s = float(os.environ.get("PARECER_INTERVALO_S", "6.0"))

    for id_lote in ids:
        try:
            r = parecer_ia.obter_parecer(id_lote=id_lote, conn=conn, user=_usuario_sistema())
            origem = r.get("origem", "desconhecido")
            contagem[origem] = contagem.get(origem, 0) + 1
            if origem in ("IA", "FALLBACK_TEMPLATE"):
                time.sleep(intervalo_s)
        except Exception as e:
            conn.rollback()
            contagem["erro"] += 1
            print(f"[AGENDADOR] parecer_ia lote {id_lote}: {getattr(e, 'detail', e)}")
    texto = f"{len(ids)} lote(s): {contagem.get('IA', 0)} gerado(s) pela IA, {contagem.get('CACHE', 0)} em cache, {contagem.get('SEM_DADOS', 0)} sem dados"
    if contagem.get("FALLBACK_TEMPLATE", 0):
        texto += f", {contagem['FALLBACK_TEMPLATE']} com texto de reserva (IA indisponível)"
    if contagem.get("erro", 0):
        texto += f", {contagem['erro']} com erro"
    return texto


def _parecer_ia() -> str:
    return _com_conexao(pre_aquecer_pareceres)


# (nome, variável do .env, padrão em minutos, função). A ordem importa: o prejuízo e os alertas
# preditivos leem o risco mais recente, e o parecer de IA lê tudo o que veio antes.
TAREFAS: List[Tuple[str, str, int, Callable[[], object]]] = [
    ("risco_climatico", "AGENDADOR_RISCO_MIN", 180, _risco_climatico),
    ("janela_colheita", "AGENDADOR_JANELA_MIN", 360, _janela_colheita),
    ("irrigacao", "AGENDADOR_IRRIGACAO_MIN", 360, _irrigacao),
    ("prejuizo", "AGENDADOR_PREJUIZO_MIN", 360, _prejuizo),
    ("alertas_preditivos", "AGENDADOR_PREDITIVO_MIN", 180, _alertas_preditivos),
    ("parecer_ia", "AGENDADOR_PARECER_MIN", 15, _parecer_ia),
]

_proxima: Dict[str, float] = {}


def reiniciar() -> None:
    """Esquece o que já rodou (usado nos testes)."""
    _proxima.clear()


def _motivo(e: Exception) -> str:
    return str(getattr(e, "detail", None) or e)


def executar_pendentes(agora: Optional[float] = None, tarefas=None) -> Dict[str, str]:
    """Roda as tarefas que já passaram da hora. Devolve {nome: resultado} só das que rodaram."""
    if not _env_bool("AGENDADOR_ATIVO", True):
        return {}
    agora = time.monotonic() if agora is None else agora
    na_partida = _env_bool("AGENDADOR_EXECUTAR_NA_PARTIDA", True)
    retry_s = _env_int("AGENDADOR_RETRY_MIN", 15) * 60
    resultado: Dict[str, str] = {}

    for nome, var, padrao_min, fn in (tarefas if tarefas is not None else TAREFAS):
        intervalo_s = _env_int(var, padrao_min) * 60
        if nome not in _proxima:                       # primeira vez que vemos a tarefa
            _proxima[nome] = agora if na_partida else agora + intervalo_s
        if agora < _proxima[nome]:
            continue
        try:
            detalhe = fn()
            resultado[nome] = "ok" + (f" ({_n_ou_texto(detalhe)})" if detalhe is not None else "")
            _proxima[nome] = agora + intervalo_s
        except Exception as e:
            resultado[nome] = f"falhou: {_motivo(e)}"
            _proxima[nome] = agora + retry_s
    return resultado


def _n_ou_texto(detalhe) -> str:
    return f"{detalhe} registro(s)" if isinstance(detalhe, int) else str(detalhe)


def iniciar_em_segundo_plano() -> Optional[threading.Thread]:
    """Inicia a thread do agendador (daemon: morre junto com o main.py). Chame uma vez só."""
    if not _env_bool("AGENDADOR_ATIVO", True):
        print("[AGENDADOR] desligado (AGENDADOR_ATIVO=false)")
        return None
    tick = _env_int("AGENDADOR_TICK_S", 30)

    def _loop():
        while True:
            try:
                for nome, r in executar_pendentes().items():
                    print(f"[AGENDADOR] {nome}: {r}")
            except Exception as e:  # nunca deixa a thread morrer
                print(f"[ERRO] agendador: {e}")
            time.sleep(tick)

    t = threading.Thread(target=_loop, name="agendador", daemon=True)
    t.start()
    print("[AGENDADOR] iniciado em segundo plano")
    return t