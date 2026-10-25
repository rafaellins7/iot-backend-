from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from src.api import calculos_previsao as calc
from src.api.deps import get_conn

router = APIRouter(prefix="/recomendacoes", tags=["recomendacoes"])


class Recomendacao(BaseModel):
    tipo: str
    prioridade: str          # baixa | media | alta
    mensagem: str


class RecomendacoesOut(BaseModel):
    id_lote: int
    recomendacoes: List[Recomendacao]


@router.get("", response_model=RecomendacoesOut)
def recomendacoes_por_lote(id_lote: int = Query(...), conn=Depends(get_conn)):
    """Regras iniciais (árvore de decisão manual) sobre as últimas previsões gravadas do lote."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT 1 FROM lote WHERE id_lote = %s", (id_lote,))
        if cur.fetchone() is None:
            raise HTTPException(404, "Lote não encontrado")
        cur.execute("""SELECT i.necessita_irrigacao, i.quantidade_agua_mm, i.temperatura, i.umidade,
                              p.vpd_limite_kpa
                       FROM previsao_irrigacao i
                       JOIN lote l ON l.id_lote = i.fk_lote_id_lote
                       LEFT JOIN parametro_irrigacao p ON p.fk_fruta_id_fruta = l.fk_fruta_id_fruta
                       WHERE i.fk_lote_id_lote = %s ORDER BY i.data_previsao DESC LIMIT 1""", (id_lote,))
        irr = cur.fetchone()
        cur.execute("""SELECT prejuizo_estimado FROM previsao_prejuizo
                       WHERE fk_lote_id_lote = %s ORDER BY data_previsao DESC LIMIT 1""", (id_lote,))
        prej = cur.fetchone()
        cur.execute("""SELECT nivel_risco, justificativa FROM risco_climatico
                       WHERE fk_lote_id_lote = %s ORDER BY data_previsao DESC LIMIT 1""", (id_lote,))
        risco = cur.fetchone()
        cur.execute("""SELECT resultado FROM previsao WHERE fk_lote_id_lote = %s AND tipo = 'janela_colheita'
                       ORDER BY gerado_em DESC LIMIT 1""", (id_lote,))
        janela = cur.fetchone()

    nivel = calc.normalizar_nivel(risco["nivel_risco"]) if risco else None
    recs = []
    if irr:
        if irr["necessita_irrigacao"]:
            recs.append(("irrigacao", "media", f"Irrigar cerca de {irr['quantidade_agua_mm']} mm/dia."))
        if irr["temperatura"] is not None and irr["umidade"] is not None and irr["vpd_limite_kpa"] is not None \
                and calc.vpd_kpa(float(irr["temperatura"]), float(irr["umidade"])) >= float(irr["vpd_limite_kpa"]):
            recs.append(("irrigacao", "alta", "VPD acima do limite da cultura: demanda atmosférica elevada."))
    if prej and prej["prejuizo_estimado"] and float(prej["prejuizo_estimado"]) > 0:
        recs.append(("logistica", "alta" if nivel == "alto" else "media",
                     f"Prejuízo estimado de R$ {float(prej['prejuizo_estimado']):.2f}: verifique a "
                     "temperatura do lote e priorize o escoamento."))
    if nivel == "alto":
        recs.append(("clima", "alta", risco["justificativa"] or "Risco climático alto nos próximos dias."))
    if janela and janela["resultado"]:
        recs.append(("colheita", "baixa", janela["resultado"]))
    if not recs:
        recs.append(("geral", "baixa", "Sem ações recomendadas no momento."))
    return {"id_lote": id_lote,
            "recomendacoes": [{"tipo": t, "prioridade": p, "mensagem": m} for t, p, m in recs]}