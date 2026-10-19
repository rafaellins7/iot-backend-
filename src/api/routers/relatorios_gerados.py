"""Histórico de relatórios (tabela relatorio) + geração e exportação em CSV.
A tabela relatorio guarda só os metadados; o conteúdo é recalculado a partir de
tipo + período + parametros """

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, Field

from src.api.auditoria import auditar
from src.api.deps import get_conn
from src.api.filtros import clausula
from src.api.routers.relatorios import _LEITURAS_AVALIADAS, _UNIDADE_TRUNC

router = APIRouter(prefix="/relatorios", tags=["relatorios"])

Tipo = Literal["saidas_faixa", "leituras_diarias", "alertas"]
Agrupamento = Literal["dia", "semana", "mes"]

COLUNAS = {
    "saidas_faixa": ["periodo", "total_leituras", "saidas_faixa", "saidas_temperatura",
                     "saidas_umidade", "pct_fora"],
    "leituras_diarias": ["id_lote", "dia", "temp_media", "temp_min", "temp_max",
                         "umid_media", "umid_min", "umid_max", "qtd_leituras"],
    "alertas": ["id_alerta", "data_hora", "tipo_alerta", "descricao", "nivel", "status",
                "preditivo", "id_lote"],
}


class RelatorioIn(BaseModel):
    tipo: Tipo
    inicio: date
    fim: date
    id_lote: Optional[int] = None
    agrupamento: Agrupamento = "dia"          # só vale para saidas_faixa
    descricao: Optional[str] = Field(default=None, max_length=150)
    id_usuario: Optional[int] = None          # até existir autenticação, vem do cliente


class RelatorioMeta(BaseModel):
    id_relatorio: int
    tipo: Optional[str] = None
    descricao: Optional[str] = None
    data_geracao: Optional[date] = None
    inicio: Optional[date] = None
    fim: Optional[date] = None
    id_usuario: Optional[int] = None
    parametros: Optional[dict] = None


class RelatorioCompleto(BaseModel):
    relatorio: RelatorioMeta
    dados: List[dict]


SELECT_META = """
    SELECT id_relatorio, tipo, descricao, data_geracao, inicio, fim,
           fk_usuario_id_usuario AS id_usuario, parametros
    FROM relatorio
"""


def _limpar(linhas: List[dict]) -> List[dict]:
    """Decimal -> float e datas -> ISO 8601, para o JSON e o CSV."""
    saida = []
    for r in linhas:
        n = {}
        for k, v in r.items():
            if isinstance(v, Decimal):
                v = float(v)
            elif isinstance(v, (datetime, date)):
                v = v.isoformat()
            n[k] = v
        saida.append(n)
    return saida


# ------------------------------------------------------------------ geradores
def _saidas_faixa(cur, inicio: date, fim: date, p: dict) -> List[dict]:
    where = ["l.data_hora >= %s", "l.data_hora < %s"]
    params = [inicio, fim + timedelta(days=1)]
    if p.get("id_lote") is not None:
        where.append("lo.id_lote = %s")
        params.append(p["id_lote"])
    cur.execute(f"""
        WITH leituras_avaliadas AS ({_LEITURAS_AVALIADAS + clausula(where)})
        SELECT date_trunc(%s, data_hora) AS periodo,
               COUNT(*)::int AS total_leituras,
               COUNT(*) FILTER (WHERE temp_fora OR umid_fora)::int AS saidas_faixa,
               COUNT(*) FILTER (WHERE temp_fora)::int AS saidas_temperatura,
               COUNT(*) FILTER (WHERE umid_fora)::int AS saidas_umidade
        FROM leituras_avaliadas GROUP BY periodo ORDER BY periodo
    """, params + [_UNIDADE_TRUNC[p.get("agrupamento", "dia")]])
    linhas = cur.fetchall()
    for r in linhas:
        r["pct_fora"] = round(100 * r["saidas_faixa"] / r["total_leituras"], 1) if r["total_leituras"] else None
    return linhas


def _leituras_diarias(cur, inicio: date, fim: date, p: dict) -> List[dict]:
    sql = """SELECT id_lote, dia, ROUND(temp_media::numeric, 2) AS temp_media,
                    ROUND(temp_min::numeric, 2) AS temp_min, ROUND(temp_max::numeric, 2) AS temp_max,
                    ROUND(umid_media::numeric, 2) AS umid_media,
                    ROUND(umid_min::numeric, 2) AS umid_min, ROUND(umid_max::numeric, 2) AS umid_max,
                    qtd_leituras
             FROM vw_leituras_diarias_lote WHERE dia BETWEEN %s AND %s"""
    params = [inicio, fim]
    if p.get("id_lote") is not None:
        sql += " AND id_lote = %s"
        params.append(p["id_lote"])
    cur.execute(sql + " ORDER BY id_lote, dia", params)
    return cur.fetchall()


def _alertas(cur, inicio: date, fim: date, p: dict) -> List[dict]:
    sql = """SELECT a.id_alerta, a.data_hora, a.tipo_alerta, a.descricao, a.nivel::text AS nivel,
                    a.status, (a.fk_previsao_id_previsao IS NOT NULL) AS preditivo,
                    COALESCE(s.fk_lote_id_lote, pv.fk_lote_id_lote) AS id_lote
             FROM alerta a
             LEFT JOIN leitura_climatica r ON r.id_leitura = a.fk_leitura_id_leitura
             LEFT JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
             LEFT JOIN previsao pv ON pv.id_previsao = a.fk_previsao_id_previsao
             WHERE a.data_hora >= %s AND a.data_hora < %s"""
    params = [inicio, fim + timedelta(days=1)]
    if p.get("id_lote") is not None:
        sql += " AND COALESCE(s.fk_lote_id_lote, pv.fk_lote_id_lote) = %s"
        params.append(p["id_lote"])
    cur.execute(sql + " ORDER BY a.data_hora", params)
    return cur.fetchall()


GERADORES = {"saidas_faixa": _saidas_faixa, "leituras_diarias": _leituras_diarias, "alertas": _alertas}


def _gerar_dados(cur, meta: dict) -> List[dict]:
    p = meta.get("parametros") or {}
    return _limpar(GERADORES[meta["tipo"]](cur, meta["inicio"], meta["fim"], p))


def _buscar_meta(cur, id_relatorio: int) -> dict:
    cur.execute(SELECT_META + " WHERE id_relatorio = %s", (id_relatorio,))
    meta = cur.fetchone()
    if meta is None:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    if meta["tipo"] not in GERADORES:
        raise HTTPException(status_code=422, detail=f"Tipo de relatório sem gerador: {meta['tipo']}")
    return meta


# ------------------------------------------------------------------ endpoints
@router.post("", response_model=RelatorioCompleto, status_code=201)
def gerar_relatorio(dados: RelatorioIn, request: Request, conn=Depends(get_conn)):
    if dados.inicio > dados.fim:
        raise HTTPException(status_code=400, detail="'inicio' não pode ser maior que 'fim'")

    with auditar(request, "gerar relatorio") as ctx:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if dados.id_usuario is not None:
                cur.execute("SELECT 1 FROM usuario WHERE id_usuario = %s", (dados.id_usuario,))
                if cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail="Usuário não encontrado")
                ctx.id_usuario = dados.id_usuario  # só depois de validar (FK do log_acesso)
            if dados.id_lote is not None:
                cur.execute("SELECT 1 FROM lote WHERE id_lote = %s", (dados.id_lote,))
                if cur.fetchone() is None:
                    raise HTTPException(status_code=404, detail="Lote não encontrado")

            parametros = {"id_lote": dados.id_lote}
            if dados.tipo == "saidas_faixa":
                parametros["agrupamento"] = dados.agrupamento
            cur.execute(
                """INSERT INTO relatorio (tipo, descricao, data_geracao, inicio, fim,
                                          fk_usuario_id_usuario, parametros)
                   VALUES (%s, %s, (now() AT TIME ZONE 'UTC')::date, %s, %s, %s, %s)
                   RETURNING id_relatorio""",
                (dados.tipo, dados.descricao, dados.inicio, dados.fim, dados.id_usuario, Json(parametros)),
            )
            id_novo = cur.fetchone()["id_relatorio"]
            ctx.detalhe = f"id={id_novo} tipo={dados.tipo}"
            cur.execute(SELECT_META + " WHERE id_relatorio = %s", (id_novo,))
            meta = cur.fetchone()
            conteudo = _gerar_dados(cur, meta)
        conn.commit()
    return {"relatorio": meta, "dados": conteudo}


@router.get("", response_model=List[RelatorioMeta])
def listar_relatorios(tipo: Optional[Tipo] = None, limite: int = Query(50, ge=1, le=500),
                      conn=Depends(get_conn)):
    sql, params = SELECT_META, []
    if tipo:
        sql += " WHERE tipo = %s"
        params.append(tipo)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql + " ORDER BY id_relatorio DESC LIMIT %s", params + [limite])
        return cur.fetchall()


@router.get("/{id_relatorio:int}", response_model=RelatorioCompleto)
def obter_relatorio(id_relatorio: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        meta = _buscar_meta(cur, id_relatorio)
        return {"relatorio": meta, "dados": _gerar_dados(cur, meta)}


@router.get("/{id_relatorio:int}/csv")
def exportar_csv(id_relatorio: int, request: Request, conn=Depends(get_conn)):
    with auditar(request, "exportar relatorio") as ctx:
        ctx.detalhe = f"id={id_relatorio}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            meta = _buscar_meta(cur, id_relatorio)
            linhas = _gerar_dados(cur, meta)

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUNAS[meta["tipo"]], delimiter=";", extrasaction="ignore")
    w.writeheader()
    w.writerows(linhas)
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="relatorio_{id_relatorio}_{meta["tipo"]}.csv"'},
    )