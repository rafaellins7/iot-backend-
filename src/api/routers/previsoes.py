from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel

from src.api.routers import previsao_regras as regras
from src.api.auditoria import auditar
from src.api.deps import get_conn
from src.api.routers import clima

router = APIRouter(prefix="/previsoes", tags=["previsoes"])


class JanelaColheitaOut(BaseModel):
    id_previsao: int
    id_lote: int
    fruta: Optional[str] = None
    gerado_em: Optional[str] = None      # ISO 8601 (o banco guarda UTC sem fuso)
    janela_inicio: Optional[str] = None
    janela_fim: Optional[str] = None
    n_dias: int = 0
    probabilidade: Optional[float] = None
    categoria: Optional[str] = None
    resultado: Optional[str] = None
    modelo: Optional[str] = None
    faixa_campo: Optional[bool] = None
    dias: list = []


class RiscoGeradoOut(BaseModel):
    id_risco_climatico: int
    id_lote: int
    nivel_risco: str
    probabilidade: Optional[float] = None
    justificativa: Optional[str] = None
    periodo_inicio: Optional[str] = None
    periodo_fim: Optional[str] = None


def _id_modelo(cur, nome: str, tipo_modelo: str, finalidade: str) -> int:
    cur.execute("SELECT id_modelo FROM ia_modelo WHERE nome = %s", (nome,))
    linha = cur.fetchone()
    if linha:
        return linha["id_modelo"]
    cur.execute(
        """INSERT INTO ia_modelo (nome, tipo_modelo, finalidade, algoritmo, versao, status)
           VALUES (%s, %s, %s, 'limiares', '1', 'ativo') RETURNING id_modelo""",
        (nome, tipo_modelo, finalidade),
    )
    return cur.fetchone()["id_modelo"]


def _lotes_em_campo(cur, id_lote: Optional[int]) -> List[dict]:
    """Lotes em campo (Em produção / Pronto para colheita). Com id_lote: valida e devolve só ele."""
    if id_lote is not None:
        cur.execute(
            """SELECT id_lote, fk_fruta_id_fruta AS id_fruta, fn_etapa_lote(status) AS etapa
               FROM lote WHERE id_lote = %s""", (id_lote,))
        lote = cur.fetchone()
        if lote is None:
            raise HTTPException(status_code=404, detail="Lote não encontrado")
        if lote["etapa"] != "campo":
            raise HTTPException(status_code=409, detail="O lote já foi colhido: a previsão vale só para lotes em campo")
        return [lote]
    cur.execute(
        """SELECT id_lote, fk_fruta_id_fruta AS id_fruta FROM lote
           WHERE fn_etapa_lote(status) = 'campo' ORDER BY id_lote""")
    return cur.fetchall()


def _faixa_campo(cur, id_fruta: Optional[int]) -> Optional[dict]:
    if id_fruta is None:
        return None
    cur.execute(
        """SELECT temp_min, temp_max FROM config_parametro
           WHERE fk_fruta_id_fruta = %s AND etapa = 'campo' LIMIT 1""", (id_fruta,))
    return cur.fetchone()


def _iso(v):
    return v.isoformat() if v is not None else None


def _saida_janela(r: dict) -> dict:
    det = r.pop("detalhes", None) or {}
    janela = det.get("janela") or {}
    r["gerado_em"] = _iso(r["gerado_em"])
    r["probabilidade"] = float(r["probabilidade"]) if r["probabilidade"] is not None else None
    r.update(janela_inicio=janela.get("inicio"), janela_fim=janela.get("fim"),
             n_dias=janela.get("n_dias", 0), faixa_campo=det.get("faixa_campo"),
             dias=det.get("dias", []))
    return r


_SELECT_JANELA = """
    SELECT {distinct} p.id_previsao, p.fk_lote_id_lote AS id_lote, f.nome AS fruta,
           p.gerado_em, p.probabilidade, p.categoria::text AS categoria, p.resultado,
           p.modelo_ultilizado AS modelo, p.detalhes
    FROM previsao p
    JOIN lote l ON l.id_lote = p.fk_lote_id_lote
    LEFT JOIN fruta f ON f.id_fruta = l.fk_fruta_id_fruta
    WHERE p.tipo = 'janela_colheita'
"""


@router.get("/janela-colheita", response_model=List[JanelaColheitaOut])
def janela_colheita(id_lote: Optional[int] = None, limite: int = Query(30, ge=1, le=200),
                    conn=Depends(get_conn)):
    """Sem id_lote: a última janela de cada lote. Com id_lote: histórico (mais recentes primeiro)."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if id_lote is None:
            cur.execute(_SELECT_JANELA.format(distinct="DISTINCT ON (p.fk_lote_id_lote)")
                        + " ORDER BY p.fk_lote_id_lote, p.gerado_em DESC")
        else:
            cur.execute(_SELECT_JANELA.format(distinct="")
                        + " AND p.fk_lote_id_lote = %s ORDER BY p.gerado_em DESC LIMIT %s",
                        (id_lote, limite))
        return [_saida_janela(r) for r in cur.fetchall()]


@router.post("/janela-colheita/gerar", response_model=List[JanelaColheitaOut], status_code=201)
def gerar_janela_colheita(
    request: Request,
    id_lote: Optional[int] = Query(None, description="Sem id_lote: todos os lotes em campo"),
    dias: int = Query(7, ge=3, le=7),
    conn=Depends(get_conn),
):
    with auditar(request, "gerar janela de colheita") as ctx:
        ctx.detalhe = f"lote={id_lote}" if id_lote is not None else "todos"
        previsao = clima.previsao(dias=dias, latitude=None, longitude=None)  # usa o cache da Open-Meteo
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            lotes = _lotes_em_campo(cur, id_lote)
            saidas = []
            for lote in lotes:
                faixa = _faixa_campo(cur, lote["id_fruta"])
                j = regras.calcular_janela(previsao["dias"], faixa)
                detalhes = {
                    "janela": {"inicio": j["inicio"], "fim": j["fim"], "n_dias": j["n_dias"]},
                    "faixa_campo": j["faixa_campo"],
                    "dias": j["dias"],
                    "fonte": previsao.get("fonte"),
                    "horizonte_dias": dias,
                }
                cur.execute(
                    """INSERT INTO previsao (fk_lote_id_lote, data, probabilidade, resultado,
                                             modelo_ultilizado, tipo, categoria, detalhes)
                       VALUES (%s, %s, %s, %s, %s, 'janela_colheita', %s::nivel_alerta, %s)
                       RETURNING id_previsao""",
                    (lote["id_lote"], j["inicio"], j["probabilidade"], j["resultado"],
                     regras.modelo_janela(), j["categoria"], Json(detalhes)),
                )
                saidas.append(cur.fetchone()["id_previsao"])
            ids = tuple(saidas)
            cur.execute(_SELECT_JANELA.format(distinct="")
                        + " AND p.id_previsao IN %s ORDER BY p.fk_lote_id_lote", (ids or (0,),))
            resposta = [_saida_janela(r) for r in cur.fetchall()]
        conn.commit()
    return resposta


@router.post("/risco-climatico/gerar", response_model=List[RiscoGeradoOut], status_code=201)
def gerar_risco_climatico(
    request: Request,
    id_lote: Optional[int] = Query(None, description="Sem id_lote: todos os lotes em campo"),
    dias: int = Query(3, ge=1, le=7),
    conn=Depends(get_conn),
):
    """Grava em risco_climatico (uma linha por lote). A previsão é a mesma para todos os
    lotes, pois só há uma coordenada de referência (CLIMA_LATITUDE/CLIMA_LONGITUDE)."""
    with auditar(request, "gerar risco climatico") as ctx:
        ctx.detalhe = f"lote={id_lote}" if id_lote is not None else "todos"
        previsao = clima.previsao(dias=dias, latitude=None, longitude=None)
        risco = regras.calcular_risco(previsao["dias"][:dias], previsao["horas"])
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            lotes = _lotes_em_campo(cur, id_lote)
            id_modelo = _id_modelo(cur, regras.modelo_risco(), "regras", "risco_climatico")
            resposta = []
            for lote in lotes:
                cur.execute(
                    """INSERT INTO risco_climatico
                         (fk_lote_id_lote, fk_modelo_id_modelo, temperatura, umidade,
                          periodo_inicio, periodo_fim, nivel_risco, probabilidade, justificativa)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id_risco_climatico""",
                    (lote["id_lote"], id_modelo, risco["temperatura"], risco["umidade"],
                     risco["periodo_inicio"], risco["periodo_fim"], risco["nivel_risco"],
                     risco["probabilidade"], risco["justificativa"]),
                )
                resposta.append({
                    "id_risco_climatico": cur.fetchone()["id_risco_climatico"],
                    "id_lote": lote["id_lote"],
                    "nivel_risco": risco["nivel_risco"],
                    "probabilidade": risco["probabilidade"],
                    "justificativa": risco["justificativa"],
                    "periodo_inicio": risco["periodo_inicio"],
                    "periodo_fim": risco["periodo_fim"],
                })
        conn.commit()
    return resposta