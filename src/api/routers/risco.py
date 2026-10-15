from fastapi import APIRouter, Depends

from ..deps import get_conn  

router = APIRouter(prefix="/riscos", tags=["riscos"])


def _num(v):
    return float(v) if v is not None else None


def _rows(cur):
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/prejuizo")
def risco_prejuizo(id_lote: int | None = None, limite: int = 30, conn=Depends(get_conn)):
    """Sem id_lote: última previsão de cada lote.
    Com id_lote: histórico das previsões desse lote (mais recentes primeiro)."""
    with conn.cursor() as cur:
        if id_lote is None:
            cur.execute("""
                SELECT DISTINCT ON (pp.fk_lote_id_lote)
                       l.id_lote, l.destino, l.quantidade, l.unidade,
                       pp.prejuizo_estimado, pp.temperatura, pp.umidade,
                       pp.periodo_inicio, pp.periodo_fim, pp.data_previsao,
                       m.nome AS modelo
                FROM previsao_prejuizo pp
                JOIN lote l      ON l.id_lote = pp.fk_lote_id_lote
                JOIN ia_modelo m ON m.id_modelo = pp.fk_modelo_id_modelo
                ORDER BY pp.fk_lote_id_lote, pp.data_previsao DESC
            """)
        else:
            cur.execute("""
                SELECT l.id_lote, l.destino, l.quantidade, l.unidade,
                       pp.prejuizo_estimado, pp.temperatura, pp.umidade,
                       pp.periodo_inicio, pp.periodo_fim, pp.data_previsao,
                       m.nome AS modelo
                FROM previsao_prejuizo pp
                JOIN lote l      ON l.id_lote = pp.fk_lote_id_lote
                JOIN ia_modelo m ON m.id_modelo = pp.fk_modelo_id_modelo
                WHERE pp.fk_lote_id_lote = %s
                ORDER BY pp.data_previsao DESC
                LIMIT %s
            """, (id_lote, limite))
        itens = _rows(cur)

    for i in itens:
        i["prejuizo_estimado"] = _num(i["prejuizo_estimado"])
        i["umidade"] = _num(i["umidade"])
    return itens


@router.get("/climatico")
def risco_climatico(
    id_lote: int | None = None,
    nivel: str | None = None,
    limite: int = 30,
    conn=Depends(get_conn),
):
    """Sem id_lote: último risco climático de cada lote (filtrável por nivel).
    Com id_lote: histórico desse lote (mais recentes primeiro)."""
    with conn.cursor() as cur:
        if id_lote is None:
            sql = """
                SELECT * FROM (
                    SELECT DISTINCT ON (rc.fk_lote_id_lote)
                           l.id_lote, l.destino,
                           rc.nivel_risco, rc.probabilidade, rc.justificativa,
                           rc.temperatura, rc.umidade,
                           rc.periodo_inicio, rc.periodo_fim, rc.data_previsao,
                           m.nome AS modelo
                    FROM risco_climatico rc
                    JOIN lote l      ON l.id_lote = rc.fk_lote_id_lote
                    JOIN ia_modelo m ON m.id_modelo = rc.fk_modelo_id_modelo
                    ORDER BY rc.fk_lote_id_lote, rc.data_previsao DESC
                ) ult
            """
            params = []
            if nivel:
                sql += " WHERE ult.nivel_risco = %s"
                params.append(nivel)
            sql += " ORDER BY ult.data_previsao DESC"
            cur.execute(sql, params)
        else:
            cur.execute("""
                SELECT l.id_lote, l.destino,
                       rc.nivel_risco, rc.probabilidade, rc.justificativa,
                       rc.temperatura, rc.umidade,
                       rc.periodo_inicio, rc.periodo_fim, rc.data_previsao,
                       m.nome AS modelo
                FROM risco_climatico rc
                JOIN lote l      ON l.id_lote = rc.fk_lote_id_lote
                JOIN ia_modelo m ON m.id_modelo = rc.fk_modelo_id_modelo
                WHERE rc.fk_lote_id_lote = %s
                ORDER BY rc.data_previsao DESC
                LIMIT %s
            """, (id_lote, limite))
        itens = _rows(cur)

    for i in itens:
        i["probabilidade"] = _num(i["probabilidade"])
        i["umidade"] = _num(i["umidade"])
    return itens