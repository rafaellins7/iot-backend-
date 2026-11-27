import hashlib
import ipaddress
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, Field

from src.api.deps import get_conn
from src.api.deps_auth import get_current_user
from src.api.escopo import exigir_lote, filtrar_por_dono
from src.api.services.llm_client import LLMError, gerar_json
from src.api.services.parecer_prompt import (
    SYSTEM_PROMPT, montar_prompt_usuario, parecer_template, secoes_para_texto, validar_saida)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/pareceres", tags=["pareceres"])

NOME_MODELO = "Parecer Agronômico"
LIMITE_DETALHES = 1500      # caracteres de `detalhes` (JSONB da previsão) enviados à IA
LIMITE_TEXTO = 8000


# ---------- helpers ----------

def _uid(user):
    if isinstance(user, dict):
        return user.get("id_usuario") or user.get("id")
    return getattr(user, "id_usuario", None) or getattr(user, "id", None)


def _limpar(o):
    """Decimal -> float, datas -> ISO, para o dict poder ir ao JSONB e ao prompt."""
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, dict):
        return {k: _limpar(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_limpar(v) for v in o]
    return o


def _hash(dados: dict) -> str:
    base = {k: v for k, v in dados.items() if k != "referencia"}
    return hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _auditar(cur, request: Request, user, acao: str, resultado: str):
    ip = request.client.host if request.client else None
    try:
        ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        ip = None
    cur.execute(
        "INSERT INTO log_acesso (data_hora, acao, ip, resultado, fk_usuario_id_usuario) "
        "VALUES ((now() AT TIME ZONE 'UTC'), %s, %s, %s, %s)",
        (acao[:60], ip, resultado[:150], _uid(user)),
    )


_CTE_BASE = """
WITH base AS (
  SELECT s.ambiente,
         CASE WHEN r.origem = 'simulado' OR s.tipo_sensor = 'simulado'
              THEN 'simulado' ELSE 'real' END AS origem,
         r.data_hora,
         r.temperatura AS t,
         r.umidade AS u
  FROM leitura_climatica r
  JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
  WHERE s.fk_lote_id_lote = %(lote)s
    AND r.data_hora BETWEEN %(ini)s AND %(fim)s
)
"""


def _tabela_existe(cur, nome: str) -> bool:
    """Tabela opcional: se não existir no banco, o parecer segue sem esse bloco de dados."""
    cur.execute("SELECT to_regclass(%s) IS NOT NULL AS ok", (f"public.{nome}",))
    return cur.fetchone()["ok"]


def coletar_dados(cur, id_lote: int, tipo: str, dias: int) -> dict:
    cur.execute(
        """SELECT l.id_lote, l.quantidade, l.unidade, l.destino, l.data_colheita,
                  l.status::text AS status, fn_etapa_lote(l.status) AS etapa,
                  l.fk_fruta_id_fruta, f.nome AS fruta
           FROM lote l JOIN fruta f ON f.id_fruta = l.fk_fruta_id_fruta
           WHERE l.id_lote = %s""", (id_lote,))
    lote = cur.fetchone()
    if not lote:
        raise HTTPException(404, "Lote não encontrado")

    cur.execute(
        """SELECT c.etapa, c.temp_min, c.temp_max, c.umidade_min AS umid_min,
                  c.umidade_max AS umid_max
           FROM config_parametro c
           WHERE c.fk_fruta_id_fruta = %s
             AND (c.etapa = %s OR (%s = 'transporte' AND c.etapa = 'armazenamento'))
           ORDER BY (c.etapa = %s) DESC LIMIT 1""",
        (lote["fk_fruta_id_fruta"], lote["etapa"], lote["etapa"], lote["etapa"]))
    faixa = cur.fetchone()

    # a janela termina na última leitura do sensor de ar (a conformidade depende dele);
    # se não houver, na última leitura de qualquer sensor. Assim, sensor parado
    # não deixa o parecer vazio e o período analisado fica explícito.
    cur.execute(
        """SELECT COALESCE(max(r.data_hora) FILTER (WHERE s.ambiente = 'ar'),
                           max(r.data_hora)) AS ultima
           FROM leitura_climatica r
           JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
           WHERE s.fk_lote_id_lote = %s""", (id_lote,))
    ultima = cur.fetchone()["ultima"]
    agora = datetime.utcnow()
    fim = ultima or agora
    ini = fim - timedelta(days=dias)
    p = {"lote": id_lote, "ini": ini, "fim": fim}

    cur.execute(_CTE_BASE + """
        SELECT ambiente, origem, count(*) AS n_leituras,
               round(avg(t)::numeric,1) AS temp_media, round(min(t)::numeric,1) AS temp_min,
               round(max(t)::numeric,1) AS temp_max, round(avg(u)::numeric,1) AS umid_media,
               round(min(u)::numeric,1) AS umid_min, round(max(u)::numeric,1) AS umid_max,
               round(avg(CASE WHEN ambiente = 'ar'
                    THEN 0.6108 * exp(17.27 * t / (t + 237.3)) * (1 - u / 100.0) END)::numeric, 2) AS vpd_medio,
               max(data_hora) AS ultima_leitura
        FROM base GROUP BY ambiente, origem ORDER BY ambiente, origem""", p)
    leituras = [dict(r) for r in cur.fetchall()]
    for l in leituras:
        if l["vpd_medio"] is None:
            del l["vpd_medio"]

    if faixa and leituras:
        cur.execute(_CTE_BASE + """
            , horas AS (SELECT ambiente, origem, date_trunc('hour', data_hora) AS h,
                               avg(t) AS t, avg(u) AS u FROM base GROUP BY 1,2,3)
            SELECT ambiente, origem, count(*) AS horas_total,
                   count(*) FILTER (WHERE t < %(tmin)s OR t > %(tmax)s
                                       OR u < %(umin)s OR u > %(umax)s) AS horas_fora
            FROM horas WHERE ambiente = 'ar' GROUP BY ambiente, origem""",
            {**p, "tmin": faixa["temp_min"], "tmax": faixa["temp_max"],
             "umin": faixa["umid_min"], "umax": faixa["umid_max"]})
        horas = {(h["ambiente"], h["origem"]): h for h in cur.fetchall()}
        for l in leituras:
            h = horas.get((l["ambiente"], l["origem"]))
            if h:
                l["horas_total"], l["horas_fora"] = h["horas_total"], h["horas_fora"]

    param_irr = None
    if _tabela_existe(cur, "parametro_irrigacao"):
        cur.execute(
            """SELECT vpd_limite_kpa, aprovado FROM parametro_irrigacao
               WHERE fk_fruta_id_fruta = %s""", (lote["fk_fruta_id_fruta"],))
        param_irr = cur.fetchone()

    cur.execute(
        """SELECT DISTINCT ON (tipo) tipo, categoria::text AS categoria, valor, unidade,
                  probabilidade, resultado, gerado_em, detalhes
           FROM previsao WHERE fk_lote_id_lote = %s AND tipo IS NOT NULL
           ORDER BY tipo, gerado_em DESC""", (id_lote,))
    previsoes = {}
    for r in cur.fetchall():
        det = r.pop("detalhes")
        if det is not None and len(json.dumps(det, default=str)) <= LIMITE_DETALHES:
            r["detalhes"] = det
        previsoes[r.pop("tipo")] = dict(r)

    cur.execute(
        """SELECT a.data_hora, a.tipo_alerta AS tipo, a.nivel::text AS nivel,
                  a.descricao, a.status
           FROM alerta a
           LEFT JOIN leitura_climatica r ON r.id_leitura = a.fk_leitura_id_leitura
           LEFT JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
           LEFT JOIN previsao pv ON pv.id_previsao = a.fk_previsao_id_previsao
           WHERE (s.fk_lote_id_lote = %(l)s OR pv.fk_lote_id_lote = %(l)s)
             AND a.data_hora >= %(ini)s
           ORDER BY a.data_hora DESC""", {"l": id_lote, "ini": ini})
    todos = cur.fetchall()
    alertas = {"total": len(todos), "recentes": [dict(a) for a in todos[:10]]}

    dados = {
        "tipo": tipo,
        "lote": {"id": lote["id_lote"], "fruta": lote["fruta"], "quantidade": lote["quantidade"],
                 "unidade": lote["unidade"], "destino": lote["destino"],
                 "data_colheita": lote["data_colheita"], "status": lote["status"],
                 "etapa": lote["etapa"]},
        "periodo": {"inicio": ini, "fim": fim, "dias": dias, "ultima_leitura": ultima},
        "faixa": dict(faixa) if faixa else None,
        "leituras": leituras,
        "vpd_limite": dict(param_irr) if param_irr else None,
        "previsoes": previsoes,
        "alertas": alertas,
        "referencia": {"data_geracao": agora.date(),
                       "defasagem_dias": (agora - ultima).days if ultima else None},
    }
    return _limpar(dados)


def _id_modelo(cur, provedor: Optional[str]) -> int:
    cur.execute("SELECT id_modelo FROM ia_modelo WHERE nome = %s LIMIT 1", (NOME_MODELO,))
    r = cur.fetchone()
    if r:
        return r["id_modelo"]
    cur.execute(
        """INSERT INTO ia_modelo (nome, tipo_modelo, finalidade, algoritmo, versao, status)
           VALUES (%s, 'generativo', 'Rascunho de parecer fitossanitário',
                   'LLM (provedor definido no .env)', '1.0', 'ativo')
           RETURNING id_modelo""", (NOME_MODELO,))
    return cur.fetchone()["id_modelo"]


def _formatar(r: dict) -> dict:
    return _limpar(dict(r))


# ---------- schemas ----------

class GerarIn(BaseModel):
    id_lote: int
    tipo: Literal["agronomico", "fisiologico"] = "agronomico"
    dias: int = Field(30, ge=1, le=180)
    forcar: bool = False        # True = gera de novo mesmo com dados iguais


class EditarIn(BaseModel):
    texto_final: str = Field(..., min_length=1, max_length=LIMITE_TEXTO)


class AssinarIn(BaseModel):
    assinante_nome: str = Field(..., min_length=3, max_length=150)
    crea: str = Field(..., min_length=5, max_length=40)


def executar_geracao_parecer(
    conn,
    id_lote: int,
    tipo: Literal["agronomico", "fisiologico"] = "agronomico",
    dias: int = 30,
    forcar: bool = False,
    user=None,
    request: Optional[Request] = None,
) -> dict:
    """Executa a geração do parecer de forma segura, com verificação de hash e lock anti-duplicação.
    Reaproveitada tanto pelo endpoint manual (Produtor/Analista) quanto pelo agendador automático."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # 1. Verifica se já está em geração recente (< 5 min) para evitar duplicações simultâneas
        cur.execute(
            """SELECT * FROM parecer_agronomico
               WHERE fk_lote_id_lote = %s AND em_geracao = TRUE
                 AND gerado_em >= (now() AT TIME ZONE 'UTC') - interval '5 minutes'
               ORDER BY gerado_em DESC LIMIT 1""",
            (id_lote,),
        )
        em_curso = cur.fetchone()
        if em_curso:
            conn.commit()
            return {**_formatar(em_curso), "reaproveitado": True, "gerando": True}

        # 2. Coleta dados e calcula o hash das entradas
        dados = coletar_dados(cur, id_lote, tipo, dias)
        h = _hash(dados)

        # 3. Se não forçar, verifica se já existe parecer finalizado com sucesso para este mesmo hash
        if not forcar:
            cur.execute(
                """SELECT * FROM parecer_agronomico
                   WHERE fk_lote_id_lote = %s AND tipo = %s AND hash_entrada = %s
                     AND em_geracao = FALSE AND erro_geracao IS NULL
                     AND status IN ('rascunho', 'assinado')
                   ORDER BY gerado_em DESC LIMIT 1""",
                (id_lote, tipo, h),
            )
            ja = cur.fetchone()
            if ja:
                conn.commit()
                return {**_formatar(ja), "reaproveitado": True, "gerando": False}

        # 4. Cria registro preliminar com em_geracao = True (satisfazendo check constraints do banco)
        cur.execute(
            """INSERT INTO parecer_agronomico
                   (fk_lote_id_lote, tipo, texto_gerado, texto_final, dados_entrada,
                    hash_entrada, origem_texto, status, em_geracao, fk_gerado_por, gerado_em)
               VALUES (%s, %s, '', '', %s, %s, 'llm', 'rascunho', TRUE, %s, (now() AT TIME ZONE 'UTC'))
               RETURNING *""",
            (id_lote, tipo, Json(dados), h, _uid(user)),
        )
        rec_gerando = cur.fetchone()
        id_parecer = rec_gerando["id_parecer"]
    conn.commit()  # commit imediato para que qualquer outra requisição concorrente veja em_geracao=True

    # 5. Executa a chamada à IA (ou fallback determinístico de template)
    provedor, origem = None, "llm"
    erro_msg = None
    texto = ""
    try:
        saida, provedor = gerar_json(SYSTEM_PROMPT, montar_prompt_usuario(dados))
        secoes = validar_saida(saida, tipo)
        texto = secoes_para_texto(secoes)
    except (LLMError, ValueError) as e:
        log.warning("IA indisponível ou resposta inválida (%s); usando template", e)
        try:
            secoes = parecer_template(dados)
            origem, provedor = "template", None
            texto = secoes_para_texto(secoes)
        except Exception as e2:
            log.error("Erro fatal no fallback: %s", e2)
            erro_msg = str(e)
    except Exception as e:
        log.error("Erro inesperado na chamada ao modelo: %s", e)
        try:
            secoes = parecer_template(dados)
            origem, provedor = "template", None
            texto = secoes_para_texto(secoes)
        except Exception as e2:
            erro_msg = str(e)

    # 6. Atualiza o registro com o resultado final
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if erro_msg:
            cur.execute(
                """UPDATE parecer_agronomico
                   SET em_geracao = FALSE, erro_geracao = %s
                   WHERE id_parecer = %s RETURNING *""",
                (erro_msg[:500], id_parecer),
            )
        else:
            cur.execute(
                """UPDATE parecer_agronomico
                   SET em_geracao = FALSE, texto_gerado = %s, texto_final = %s,
                       origem_texto = %s, provedor_modelo = %s,
                       fk_modelo_id_modelo = %s, erro_geracao = NULL
                   WHERE id_parecer = %s RETURNING *""",
                (texto, texto, origem, provedor, _id_modelo(cur, provedor), id_parecer),
            )
        final = cur.fetchone()
        if request and user:
            _auditar(cur, request, user, "parecer_gerar", f"lote={id_lote} origem={origem}")
    conn.commit()
    return {**_formatar(final), "reaproveitado": False, "gerando": False}


@router.post("/gerar")
def gerar(body: GerarIn, request: Request, conn=Depends(get_conn),
          user=Depends(get_current_user)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        exigir_lote(cur, user, body.id_lote)  # 404 se o lote não existir OU for de outro dono
    return executar_geracao_parecer(
        conn=conn,
        id_lote=body.id_lote,
        tipo=body.tipo,
        dias=body.dias,
        forcar=body.forcar,
        user=user,
        request=request,
    )


@router.get("")
def listar(id_lote: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        exigir_lote(cur, user, id_lote)  # 404 se o lote não existir OU for de outro dono
        cur.execute(
            """SELECT id_parecer, fk_lote_id_lote, tipo, status, origem_texto, gerado_em,
                      assinado_em, assinante_nome, crea, em_geracao, erro_geracao, hash_entrada,
                      texto_final, texto_gerado
               FROM parecer_agronomico WHERE fk_lote_id_lote = %s
               ORDER BY gerado_em DESC""", (id_lote,))
        return [_formatar(r) for r in cur.fetchall()]


@router.get("/lote/{id_lote}/ultimo")
def obter_ultimo_por_lote(id_lote: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        exigir_lote(cur, user, id_lote)
        cur.execute(
            """SELECT * FROM parecer_agronomico
               WHERE fk_lote_id_lote = %s
               ORDER BY gerado_em DESC LIMIT 1""",
            (id_lote,),
        )
        r = cur.fetchone()
    if not r:
        return None
    return _formatar(r)


@router.get("/{id_parecer}")
def obter(id_parecer: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    where, params = ["p.id_parecer = %s"], [id_parecer]
    filtrar_por_dono(user, "l.fk_usuario_id_usuario", where, params)  # Produtor: só pareceres de lotes dele
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT p.* FROM parecer_agronomico p JOIN lote l ON l.id_lote = p.fk_lote_id_lote"
            " WHERE " + " AND ".join(where), params)
        r = cur.fetchone()
    if not r:
        raise HTTPException(404, "Parecer não encontrado")
    return _formatar(r)


def _atualizar(conn, cur, sql: str, params: tuple, id_parecer: int, msg_409: str):
    cur.execute(sql, params)
    r = cur.fetchone()
    if r:
        return r
    cur.execute("SELECT 1 FROM parecer_agronomico WHERE id_parecer = %s", (id_parecer,))
    conn.rollback()
    if not cur.fetchone():
        raise HTTPException(404, "Parecer não encontrado")
    raise HTTPException(409, msg_409)


@router.put("/{id_parecer}")
def editar(id_parecer: int, body: EditarIn, request: Request, conn=Depends(get_conn),
           user=Depends(get_current_user)):
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            r = _atualizar(
                conn, cur,
                """UPDATE parecer_agronomico SET texto_final = %s
                   WHERE id_parecer = %s AND status = 'rascunho' RETURNING *""",
                (body.texto_final.strip(), id_parecer), id_parecer,
                "Parecer já assinado; não pode ser editado")
            _auditar(cur, request, user, "parecer_editar", f"id={id_parecer}")
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    return _formatar(r)


@router.post("/{id_parecer}/assinar")
def assinar(id_parecer: int, body: AssinarIn, request: Request, conn=Depends(get_conn),
            user=Depends(get_current_user)):
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            r = _atualizar(
                conn, cur,
                """UPDATE parecer_agronomico
                   SET status = 'assinado', assinante_nome = %s, crea = %s,
                       assinado_em = (now() AT TIME ZONE 'UTC'), fk_assinado_por = %s
                   WHERE id_parecer = %s AND status = 'rascunho' RETURNING *""",
                (body.assinante_nome.strip(), body.crea.strip(), _uid(user), id_parecer),
                id_parecer, "Parecer já está assinado")
            _auditar(cur, request, user, "parecer_assinar", f"id={id_parecer}")
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    return _formatar(r)