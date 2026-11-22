"""Cadastros de apoio: propriedade, safra, variedade, porto, perda por risco e classificação."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from src.api.auditoria import auditar
from src.api.deps import get_conn
from src.api.deps_auth import get_current_user
from src.api.escopo import exigir_lote, id_dono

router = APIRouter(tags=["catalogo"])

# categoria do corte preditivo -> categoria de perda_risco (enum nivel_alerta)
CORTE_PARA_PERDA = {"BAIXO": "baixo", "MEDIO": "médio", "CRITICO": "alto"}


def _f(v):
    return None if v is None else float(v)


@router.get("/propriedades")
def listar_propriedades(conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id_propriedade, nome, codigo, cidade, uf, setor,
                   latitude, longitude, area_ha, tipo_solo, moeda_exibicao
              FROM propriedade ORDER BY nome
            """
        )
        linhas = cur.fetchall()
    for r in linhas:
        for k in ("latitude", "longitude", "area_ha"):
            r[k] = _f(r[k])
    return linhas


class PropriedadeUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1, max_length=150)
    cidade: Optional[str] = Field(default=None, max_length=80)
    uf: Optional[str] = Field(default=None, min_length=2, max_length=2)
    setor: Optional[str] = Field(default=None, max_length=40)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    area_ha: Optional[float] = Field(default=None, ge=0)
    tipo_solo: Optional[str] = Field(default=None, max_length=150)
    moeda_exibicao: Optional[str] = Field(default=None, min_length=3, max_length=3)


class SafraCreate(BaseModel):
    nome: str = Field(min_length=3, max_length=20)
    data_inicio: date
    data_fim: Optional[date] = None
    meta_ton_ha: Optional[float] = Field(default=None, ge=0)


@router.put("/propriedades/{id_propriedade}")
def atualizar_propriedade(
    id_propriedade: int, dados: PropriedadeUpdate, request: Request, conn=Depends(get_conn)
):
    campos = dados.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nenhum campo para atualizar")
    with auditar(request, "atualizar_propriedade") as ctx:
        ctx.detalhe = f"id={id_propriedade} campos={','.join(sorted(campos))}"
        sets = [f"{k} = %s" for k in campos]
        params = list(campos.values()) + [id_propriedade]
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE propriedade SET {', '.join(sets)}
                 WHERE id_propriedade = %s
                RETURNING id_propriedade, nome, codigo, cidade, uf, setor,
                          latitude, longitude, area_ha, tipo_solo, moeda_exibicao
                """,
                params,
            )
            r = cur.fetchone()
        if r is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Propriedade não encontrada")
        conn.commit()
    for k in ("latitude", "longitude", "area_ha"):
        r[k] = _f(r[k])
    return r


@router.post("/safras", status_code=201)
def criar_safra(dados: SafraCreate, request: Request, conn=Depends(get_conn)):
    if dados.data_fim is not None and dados.data_fim < dados.data_inicio:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "data_fim deve ser maior ou igual a data_inicio",
        )
    with auditar(request, "criar_safra") as ctx:
        ctx.detalhe = f"nome={dados.nome}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO safra (nome, data_inicio, data_fim, meta_ton_ha)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (nome) DO UPDATE
                   SET data_inicio = EXCLUDED.data_inicio,
                       data_fim = EXCLUDED.data_fim,
                       meta_ton_ha = EXCLUDED.meta_ton_ha
                RETURNING id_safra, nome, data_inicio, data_fim, meta_ton_ha
                """,
                (dados.nome, dados.data_inicio, dados.data_fim, dados.meta_ton_ha),
            )
            r = cur.fetchone()
        conn.commit()
    r["meta_ton_ha"] = _f(r["meta_ton_ha"])
    hoje = date.today()
    r["ativa"] = r["data_inicio"] <= hoje and (r["data_fim"] is None or r["data_fim"] >= hoje)
    return r


@router.get("/safras")
def listar_safras(conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id_safra, nome, data_inicio, data_fim, meta_ton_ha FROM safra ORDER BY data_inicio DESC"
        )
        linhas = cur.fetchall()
    hoje = date.today()
    for r in linhas:
        r["meta_ton_ha"] = _f(r["meta_ton_ha"])
        r["ativa"] = r["data_inicio"] <= hoje and (r["data_fim"] is None or r["data_fim"] >= hoje)
    return linhas


@router.get("/variedades")
def listar_variedades(id_fruta: Optional[int] = None, conn=Depends(get_conn)):
    sql = """
        SELECT v.id_variedade, v.nome, f.id_fruta, f.nome AS fruta,
               q.brix_min, q.calibre_min, q.classe
          FROM variedade v
          JOIN fruta f ON f.id_fruta = v.fk_fruta_id_fruta
          LEFT JOIN padrao_qualidade q ON q.fk_variedade_id_variedade = v.id_variedade
    """
    params = ()
    if id_fruta is not None:
        sql += " WHERE f.id_fruta = %s"
        params = (id_fruta,)
    sql += " ORDER BY f.nome, v.nome"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        linhas = cur.fetchall()
    for r in linhas:
        r["brix_min"] = _f(r["brix_min"])
    return linhas

@router.get("/portos")
def listar_portos(conn=Depends(get_conn)):
    """Portos homologados com a rota (distância e duração), quando houver."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT p.id_porto, p.nome, p.uf, p.latitude, p.longitude,
                   r.origem_nome, r.distancia_km, r.duracao_min
              FROM porto p
              LEFT JOIN rota r ON r.fk_porto_id_porto = p.id_porto
             ORDER BY p.nome
            """
        )
        linhas = cur.fetchall()
    for r in linhas:
        for k in ("latitude", "longitude", "distancia_km"):
            r[k] = _f(r[k])
    return linhas


@router.get("/perdas-risco")
def listar_perdas_risco(conn=Depends(get_conn)):
    """Fração de perda por categoria, já ligada ao nível do corte preditivo."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT categoria::text AS categoria, fracao_perda FROM perda_risco")
        linhas = cur.fetchall()
    inverso = {v: k for k, v in CORTE_PARA_PERDA.items()}
    ordem = {"baixo": 0, "médio": 1, "alto": 2}
    saida = [
        {
            "categoria": r["categoria"],
            "nivel_corte": inverso.get(r["categoria"]),
            "fracao_perda": _f(r["fracao_perda"]),
            "perda_pct": round(float(r["fracao_perda"]) * 100, 1),
        }
        for r in linhas
    ]
    return sorted(saida, key=lambda x: ordem.get(x["categoria"], 9))


class PerdaUpdate(BaseModel):
    fracao_perda: float = Field(..., ge=0.0, le=1.0)


@router.put("/perdas-risco/{categoria}")
def atualizar_perda_risco(categoria: str, dados: PerdaUpdate, request: Request, conn=Depends(get_conn)):
    with auditar(request, "atualizar_perda_risco") as ctx:
        ctx.detalhe = f"categoria={categoria}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE perda_risco SET fracao_perda = %s
                 WHERE categoria::text = %s
                RETURNING categoria::text AS categoria, fracao_perda
                """,
                (dados.fracao_perda, categoria),
            )
            r = cur.fetchone()
        if r is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Categoria não encontrada (baixo, médio ou alto)")
        conn.commit()
    return {"categoria": r["categoria"], "fracao_perda": _f(r["fracao_perda"])}


@router.get("/classificacao/resumo")
def resumo_classificacao(id_lote: Optional[int] = None, conn=Depends(get_conn), user=Depends(get_current_user)):
    """Destino da produção (lote_classificacao): kg e % por categoria."""
    sql = ("SELECT categoria, SUM(quantidade_kg) AS kg FROM lote_classificacao"
           " WHERE (%(dono)s::int IS NULL OR fk_lote_id_lote IN"
           " (SELECT id_lote FROM lote WHERE fk_usuario_id_usuario = %(dono)s))")  # Produtor: só lotes dele
    params = {"dono": id_dono(user)}
    if id_lote is not None:
        sql += " AND fk_lote_id_lote = %(id_lote)s"
        params["id_lote"] = id_lote
    sql += " GROUP BY categoria ORDER BY kg DESC"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        exigir_lote(cur, user, id_lote)  # 404 se o lote não existir OU for de outro dono
        cur.execute(sql, params)
        linhas = cur.fetchall()
    total = sum(float(r["kg"]) for r in linhas)
    return {
        "total_kg": total,
        "categorias": [
            {
                "categoria": r["categoria"],
                "quantidade_kg": float(r["kg"]),
                "percentual": round(float(r["kg"]) / total * 100, 1) if total else None,
            }
            for r in linhas
        ],
    }