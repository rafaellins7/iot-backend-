"""POST /previsoes/prejuizo/gerar, POST /previsoes/irrigacao/gerar, GET /previsoes/irrigacao.
Grava em previsao_prejuizo / previsao_irrigacao; parâmetros vêm de parametro_prejuizo / parametro_irrigacao."""
import json
import os
import urllib.request
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from src.api import calculos_previsao as calc
from src.api import previsao_repo as repo
from src.api.auditoria import auditar
from src.api.deps import get_conn
from src.api.routers.previsoes import _id_modelo, _iso, _lotes_em_campo

router = APIRouter(prefix="/previsoes", tags=["previsoes"])

MODELO_PREJUIZO = "regra_prejuizo_v1"
MODELO_IRR_CLASSIF = "regra_irrigacao_classificacao_v1"
MODELO_IRR_REGRESSAO = "regra_irrigacao_regressao_v1"


class PrejuizoOut(BaseModel):
    id_previsao_prejuizo: int
    id_lote: int
    prejuizo_estimado: Optional[float] = None
    temperatura: Optional[float] = None
    umidade: Optional[float] = None
    periodo_inicio: Optional[str] = None
    periodo_fim: Optional[str] = None
    data_previsao: Optional[str] = None
    calculo: Optional[dict] = None       # só no POST: risco, horas, preço, fração, valor da carga


class IrrigacaoOut(BaseModel):
    id_previsao_irrigacao: int
    id_lote: int
    necessita_irrigacao: bool
    quantidade_agua_mm: Optional[float] = None
    temperatura: Optional[float] = None
    umidade: Optional[float] = None
    data_previsao: Optional[str] = None
    calculo: Optional[dict] = None       # só no POST: ETc, chuva efetiva, VPD, solo simulado...


def _open_meteo_dia():
    lat, lon = os.getenv("CLIMA_LATITUDE", "-9.39"), os.getenv("CLIMA_LONGITUDE", "-40.50")
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&daily=et0_fao_evapotranspiration,precipitation_sum,precipitation_probability_max"
           "&forecast_days=1&timezone=America%2FRecife")
    with urllib.request.urlopen(url, timeout=10) as r:
        d = json.load(r)["daily"]
    return d["et0_fao_evapotranspiration"][0], d["precipitation_sum"][0], d["precipitation_probability_max"][0]


def _f(v):
    return float(v) if v is not None else None


# prejuízo
@router.post("/prejuizo/gerar", response_model=List[PrejuizoOut], status_code=201)
def gerar_prejuizo(
    request: Request,
    id_lote: Optional[int] = Query(None, description="Sem id_lote: todos os lotes não finalizados"),
    nivel_risco: Optional[str] = Query(None, description="baixo|medio|alto (padrão: último risco_climatico)"),
    horas_fora_faixa: Optional[float] = Query(None, ge=0),
    preco_kg: Optional[float] = Query(None, gt=0),
    peso_caixa_kg: Optional[float] = Query(None, gt=0),
    incluir_nao_aprovados: bool = Query(False, description="Usa parâmetros ainda não aprovados (testes)"),
    conn=Depends(get_conn),
):
    with auditar(request, "gerar previsao de prejuizo") as ctx:
        ctx.detalhe = f"lote={id_lote}" if id_lote is not None else "todos"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            lotes = repo.lotes_para_prejuizo(cur, id_lote)
            if id_lote is not None and not lotes:
                raise HTTPException(404, "Lote não encontrado ou já finalizado")
            id_modelo = _id_modelo(cur, MODELO_PREJUIZO, "regras", "prejuizo_financeiro")
            ar = repo.ultima_leitura(cur, solo=False)
            resposta = []
            for lote in lotes:
                try:
                    bruto = nivel_risco or repo.nivel_risco_atual(cur, lote["id_lote"])
                    if bruto is None:
                        raise ValueError("lote sem registro em risco_climatico (gere o risco antes)")
                    nivel = calc.normalizar_nivel(bruto)
                    par = repo.parametro_prejuizo(cur, nivel, not incluir_nao_aprovados)
                    if par is None:
                        raise ValueError(f"sem parametro_prejuizo {'aprovado ' if not incluir_nao_aprovados else ''}"
                                         f"para o nível '{nivel}'")
                    horas = horas_fora_faixa if horas_fora_faixa is not None else \
                        repo.horas_fora_da_faixa(cur, lote["id_fruta"], lote["etapa"], par["periodo_analise_dias"])
                    if horas is None:
                        raise ValueError("sem config_parametro da fruta/etapa ou sem leituras no período")
                    preco = preco_kg or repo.preco_kg_atual(cur, lote["id_fruta"], par["validade_preco_dias"])
                    if preco is None:
                        raise ValueError("sem preço de mercado dentro da validade")
                    r = calc.calcular_prejuizo(float(lote["quantidade"]), lote["unidade"], preco,
                                               float(par["fracao_perda"]), horas,
                                               float(par["tolerancia_horas"]), float(par["acrescimo_hora"]),
                                               peso_caixa_kg)
                except ValueError as e:
                    if id_lote is not None:
                        raise HTTPException(422, f"Lote {lote['id_lote']}: {e}")
                    continue  # modo "todos": pula o lote sem dados
                hoje = date.today()
                ini = hoje - timedelta(days=int(par["periodo_analise_dias"]))
                cur.execute(
                    """INSERT INTO previsao_prejuizo (fk_lote_id_lote, fk_modelo_id_modelo, temperatura,
                              umidade, periodo_inicio, periodo_fim, prejuizo_estimado)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       RETURNING id_previsao_prejuizo, data_previsao""",
                    (lote["id_lote"], id_modelo, ar and ar["temperatura"], ar and ar["umidade"],
                     ini, hoje, r["prejuizo_estimado"]))
                novo = cur.fetchone()
                resposta.append({
                    "id_previsao_prejuizo": novo["id_previsao_prejuizo"], "id_lote": lote["id_lote"],
                    "prejuizo_estimado": r["prejuizo_estimado"],
                    "temperatura": _f(ar and ar["temperatura"]), "umidade": _f(ar and ar["umidade"]),
                    "periodo_inicio": ini.isoformat(), "periodo_fim": hoje.isoformat(),
                    "data_previsao": _iso(novo["data_previsao"]),
                    "calculo": {**r, "nivel_risco": nivel, "horas_fora_faixa": horas, "preco_kg": preco,
                                "parametro_aprovado": par["aprovado"]}})
        conn.commit()
    return resposta


#irrigação
@router.post("/irrigacao/gerar", response_model=List[IrrigacaoOut], status_code=201)
def gerar_irrigacao(
    request: Request,
    id_lote: Optional[int] = Query(None, description="Sem id_lote: todos os lotes em campo"),
    chuva_registrada_mm: float = Query(0, ge=0),
    incluir_nao_aprovados: bool = Query(False, description="Usa parâmetros ainda não aprovados (testes)"),
    conn=Depends(get_conn),
):
    with auditar(request, "gerar previsao de irrigacao") as ctx:
        ctx.detalhe = f"lote={id_lote}" if id_lote is not None else "todos"
        try:
            et0, chuva_prev, prob = _open_meteo_dia()
        except Exception:
            raise HTTPException(502, "Não foi possível obter ET0 no Open-Meteo.")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            lotes = _lotes_em_campo(cur, id_lote)        # 404/409 como na janela de colheita
            ar = repo.ultima_leitura(cur, solo=False)
            solo = repo.ultima_leitura(cur, solo=True)
            vpd = calc.vpd_kpa(float(ar["temperatura"]), float(ar["umidade"])) if ar else None
            solo_umid = _f(solo["umidade"]) if solo else None
            id_classif = _id_modelo(cur, MODELO_IRR_CLASSIF, "classificacao", "irrigacao")
            id_regress = _id_modelo(cur, MODELO_IRR_REGRESSAO, "regressao", "irrigacao")
            resposta = []
            for lote in lotes:
                par = repo.parametro_irrigacao(cur, lote["id_fruta"], not incluir_nao_aprovados)
                if par is None:
                    if id_lote is not None:
                        raise HTTPException(422, f"Lote {lote['id_lote']}: sem parametro_irrigacao "
                                                 f"{'aprovado ' if not incluir_nao_aprovados else ''}para a fruta")
                    continue
                r = calc.calcular_irrigacao(
                    et0, float(par["kc"]), chuva_registrada_mm, chuva_prev or 0, prob, vpd,
                    chuva_efetiva_pct=float(par["chuva_efetiva_percentual"]),
                    prob_chuva_min=float(par["probabilidade_chuva_minima"]),
                    irrigacao_min_mm=float(par["irrigacao_minima_mm"]),
                    vpd_limite=float(par["vpd_limite_kpa"]),
                    umidade_solo=solo_umid, umidade_solo_min=float(par["umidade_solo_minima"]))
                qtd = r["necessidade_mm"] if r["precisa_irrigar"] else 0
                cur.execute(
                    """INSERT INTO previsao_irrigacao (fk_lote_id_lote, fk_modelo_classificacao,
                              fk_modelo_regressao, temperatura, umidade, necessita_irrigacao, quantidade_agua_mm)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id_previsao_irrigacao, data_previsao""",
                    (lote["id_lote"], id_classif, id_regress, ar and ar["temperatura"], ar and ar["umidade"],
                     r["precisa_irrigar"], qtd))
                novo = cur.fetchone()
                resposta.append({
                    "id_previsao_irrigacao": novo["id_previsao_irrigacao"], "id_lote": lote["id_lote"],
                    "necessita_irrigacao": r["precisa_irrigar"], "quantidade_agua_mm": qtd,
                    "temperatura": _f(ar and ar["temperatura"]), "umidade": _f(ar and ar["umidade"]),
                    "data_previsao": _iso(novo["data_previsao"]),
                    "calculo": {**r, "fase_cultura": par["fase_cultura"], "prob_chuva_pct": prob,
                                "chuva_prevista_mm": chuva_prev,
                                "umidade_solo": {"valor": solo_umid, "origem": (solo or {}).get("origem", "simulado")},
                                "parametro_aprovado": par["aprovado"]}})
        conn.commit()
    return resposta


@router.get("/irrigacao", response_model=List[IrrigacaoOut])
def consultar_irrigacao(id_lote: Optional[int] = None, limite: int = Query(30, ge=1, le=200),
                        conn=Depends(get_conn)):
    """Sem id_lote: a última previsão de cada lote. Com id_lote: histórico (mais recentes primeiro)."""
    base = """SELECT {d} id_previsao_irrigacao, fk_lote_id_lote AS id_lote, necessita_irrigacao,
                     quantidade_agua_mm, temperatura, umidade, data_previsao
              FROM previsao_irrigacao"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if id_lote is None:
            cur.execute(base.format(d="DISTINCT ON (fk_lote_id_lote)")
                        + " ORDER BY fk_lote_id_lote, data_previsao DESC")
        else:
            cur.execute(base.format(d="") + " WHERE fk_lote_id_lote = %s ORDER BY data_previsao DESC LIMIT %s",
                        (id_lote, limite))
        linhas = cur.fetchall()
    for r in linhas:
        r["data_previsao"] = _iso(r["data_previsao"])
    return linhas