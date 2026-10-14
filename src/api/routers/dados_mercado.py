from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from src.api.auditoria import auditar
from src.api.deps import get_conn
from src.api.filtros import clausula

router = APIRouter(prefix="/dados-mercado", tags=["dados-mercado"])

UnidadeMercado = Literal["kg", "caixa", "t"]  # mesmo domínio de lote.unidade (ck_lote_unidade)


class DadosMercadoCreate(BaseModel):
    id_fruta: int
    preco: float = Field(ge=0)
    unidade: UnidadeMercado = "kg"
    moeda: str = Field(default="BRL", min_length=3, max_length=3)
    demanda_exportacao: Optional[float] = Field(default=None, ge=0, le=100)
    data_referencia: Optional[date] = None


class DadosMercadoUpdate(BaseModel):
    id_fruta: Optional[int] = None
    preco: Optional[float] = Field(default=None, ge=0)
    unidade: Optional[UnidadeMercado] = None
    moeda: Optional[str] = Field(default=None, min_length=3, max_length=3)
    demanda_exportacao: Optional[float] = Field(default=None, ge=0, le=100)
    data_referencia: Optional[date] = None


class DadosMercadoOut(BaseModel):
    id_mercado: int
    id_fruta: Optional[int] = None
    fruta: Optional[str] = None
    preco: Optional[float] = None
    unidade: Optional[str] = None
    moeda: Optional[str] = None
    demanda_exportacao: Optional[float] = None
    data_referencia: Optional[date] = None


#a coluna no banco é "data_refencia" (sem o "re"); a API usa o nome correto.
SELECT_BASE = """
    SELECT d.id_mercado, d.fk_fruta_id_fruta AS id_fruta, f.nome AS fruta,
           d.preco, d.unidade, d.moeda, d.demanda_exportacao,
           d.data_refencia AS data_referencia
    FROM dados_mercado d
    LEFT JOIN fruta f ON f.id_fruta = d.fk_fruta_id_fruta
"""

COLUNAS_EDITAVEIS = {
    "id_fruta": "fk_fruta_id_fruta",
    "preco": "preco",
    "unidade": "unidade",
    "moeda": "moeda",
    "demanda_exportacao": "demanda_exportacao",
    "data_referencia": "data_refencia",
}


def _fruta_existe(cur, id_fruta: int) -> bool:
    cur.execute("SELECT 1 FROM fruta WHERE id_fruta = %s", (id_fruta,))
    return cur.fetchone() is not None


def _buscar(cur, id_mercado: int) -> Optional[dict]:
    cur.execute(SELECT_BASE + " WHERE d.id_mercado = %s", (id_mercado,))
    return cur.fetchone()


def _ou_404(dados):
    if dados is None:
        raise HTTPException(status_code=404, detail="Dado de mercado não encontrado")
    return dados


@router.get("", response_model=List[DadosMercadoOut])
def listar_dados_mercado(
    id_fruta: Optional[int] = None,
    inicio: Optional[date] = None,
    fim: Optional[date] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    if inicio and fim and inicio > fim:
        raise HTTPException(status_code=400, detail="'inicio' não pode ser maior que 'fim'")

    where, params = [], []
    if id_fruta is not None:
        where.append("d.fk_fruta_id_fruta = %s")
        params.append(id_fruta)
    if inicio:
        where.append("d.data_refencia >= %s")
        params.append(inicio)
    if fim:
        where.append("d.data_refencia <= %s")
        params.append(fim)
    sql = (SELECT_BASE + clausula(where)
           + " ORDER BY d.data_refencia DESC NULLS LAST, d.id_mercado DESC LIMIT %s OFFSET %s")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params + [limit, offset])
        return cur.fetchall()


@router.get("/{id_mercado}", response_model=DadosMercadoOut)
def obter_dados_mercado(id_mercado: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        return _ou_404(_buscar(cur, id_mercado))


@router.post("", response_model=DadosMercadoOut, status_code=201)
def criar_dados_mercado(dados: DadosMercadoCreate, request: Request, conn=Depends(get_conn)):
    with auditar(request, "criar dados_mercado") as ctx:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not _fruta_existe(cur, dados.id_fruta):
                raise HTTPException(status_code=404, detail="Fruta não encontrada")
            cur.execute(
                """
                INSERT INTO dados_mercado
                    (fk_fruta_id_fruta, preco, unidade, moeda, demanda_exportacao, data_refencia)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id_mercado
                """,
                (dados.id_fruta, dados.preco, dados.unidade, dados.moeda.upper(),
                 dados.demanda_exportacao, dados.data_referencia),
            )
            id_novo = cur.fetchone()["id_mercado"]
            ctx.detalhe = f"id={id_novo}"
            registro = _buscar(cur, id_novo)
        conn.commit()
    return registro


@router.patch("/{id_mercado}", response_model=DadosMercadoOut)
def atualizar_dados_mercado(
    id_mercado: int, dados: DadosMercadoUpdate, request: Request, conn=Depends(get_conn)
):
    campos = dados.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(status_code=400, detail="Sem dados para atualizar")

    with auditar(request, "atualizar dados_mercado") as ctx:
        ctx.detalhe = f"id={id_mercado}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if _buscar(cur, id_mercado) is None:
                raise HTTPException(status_code=404, detail="Dado de mercado não encontrado")
            if "id_fruta" in campos and not _fruta_existe(cur, campos["id_fruta"]):
                raise HTTPException(status_code=404, detail="Fruta não encontrada")

            sets, params = [], []
            for campo, valor in campos.items():
                if campo == "moeda" and valor is not None:
                    valor = valor.upper()
                sets.append(f"{COLUNAS_EDITAVEIS[campo]} = %s")
                params.append(valor)
            params.append(id_mercado)
            cur.execute(
                f"UPDATE dados_mercado SET {', '.join(sets)} WHERE id_mercado = %s", params
            )
            registro = _buscar(cur, id_mercado)
        conn.commit()
    return registro