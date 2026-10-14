from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from src.api.auditoria import auditar
from src.api.deps import get_conn

router = APIRouter(prefix="/lotes", tags=["lotes"])

StatusLote = Literal[
    "Em produção", "Pronto para colheita", "Colhido",
    "Em transporte", "Armazenado", "Finalizado",
]
UnidadeLote = Literal["kg", "caixa", "t"]  # ck_lote_unidade


class LoteCreate(BaseModel):
    id_fruta: int
    quantidade: int = Field(gt=0)
    unidade: UnidadeLote = "kg"
    status: StatusLote = "Em produção"
    destino: Optional[str] = Field(default=None, max_length=150)
    data_colheita: Optional[date] = None


class LoteUpdate(BaseModel):
    id_fruta: Optional[int] = None
    quantidade: Optional[int] = Field(default=None, gt=0)
    unidade: Optional[UnidadeLote] = None
    status: Optional[StatusLote] = None
    destino: Optional[str] = Field(default=None, max_length=150)
    data_colheita: Optional[date] = None


class LoteOut(BaseModel):
    id_lote: int
    id_fruta: Optional[int] = None
    fruta: Optional[str] = None
    quantidade: Optional[int] = None
    unidade: Optional[str] = None
    status: Optional[str] = None
    etapa: Optional[str] = None  # campo / armazenamento / transporte (fn_etapa_lote)
    destino: Optional[str] = None
    data_colheita: Optional[date] = None


SELECT_BASE = """
    SELECT l.id_lote, l.fk_fruta_id_fruta AS id_fruta, f.nome AS fruta,
           l.quantidade, l.unidade, l.status::text AS status,
           fn_etapa_lote(l.status) AS etapa,
           l.destino, l.data_colheita
    FROM lote l
    LEFT JOIN fruta f ON f.id_fruta = l.fk_fruta_id_fruta
"""

COLUNAS_EDITAVEIS = {
    "id_fruta": "fk_fruta_id_fruta",
    "quantidade": "quantidade",
    "unidade": "unidade",
    "status": "status",
    "destino": "destino",
    "data_colheita": "data_colheita",
}


def _fruta_existe(cur, id_fruta: int) -> bool:
    cur.execute("SELECT 1 FROM fruta WHERE id_fruta = %s", (id_fruta,))
    return cur.fetchone() is not None


def _buscar(cur, id_lote: int) -> Optional[dict]:
    cur.execute(SELECT_BASE + " WHERE l.id_lote = %s", (id_lote,))
    return cur.fetchone()


@router.get("", response_model=List[LoteOut])
def listar_lotes(
    status: Optional[StatusLote] = None,
    id_fruta: Optional[int] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
):
    where, params = [], []
    if status:
        where.append("l.status = %s::status_lote")
        params.append(status)
    if id_fruta is not None:
        where.append("l.fk_fruta_id_fruta = %s")
        params.append(id_fruta)
    sql = (SELECT_BASE
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY l.id_lote LIMIT %s OFFSET %s")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params + [limit, offset])
        return cur.fetchall()


@router.get("/{id_lote}", response_model=LoteOut)
def obter_lote(id_lote: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        lote = _buscar(cur, id_lote)
    if lote is None:
        raise HTTPException(status_code=404, detail="Lote não encontrado")
    return lote


@router.post("", response_model=LoteOut, status_code=201)
def criar_lote(dados: LoteCreate, request: Request, conn=Depends(get_conn)):
    with auditar(request, "criar lote") as ctx:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not _fruta_existe(cur, dados.id_fruta):
                raise HTTPException(status_code=404, detail="Fruta não encontrada")
            cur.execute(
                """
                INSERT INTO lote (fk_fruta_id_fruta, quantidade, unidade, status,
                                  destino, data_colheita)
                VALUES (%s, %s, %s, %s::status_lote, %s, %s)
                RETURNING id_lote
                """,
                (dados.id_fruta, dados.quantidade, dados.unidade, dados.status,
                 dados.destino, dados.data_colheita),
            )
            id_novo = cur.fetchone()["id_lote"]
            ctx.detalhe = f"id={id_novo}"
            lote = _buscar(cur, id_novo)
        conn.commit()
    return lote

@router.patch("/{id_lote}", response_model=LoteOut)
def atualizar_lote(id_lote: int, dados: LoteUpdate, request: Request, conn=Depends(get_conn)):
    campos = dados.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(status_code=400, detail="Sem dados para atualizar")

    with auditar(request, "atualizar lote") as ctx:
        ctx.detalhe = f"id={id_lote}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if _buscar(cur, id_lote) is None:
                raise HTTPException(status_code=404, detail="Lote não encontrado")
            if "id_fruta" in campos and not _fruta_existe(cur, campos["id_fruta"]):
                raise HTTPException(status_code=404, detail="Fruta não encontrada")

            sets, params = [], []
            for campo, valor in campos.items():
                coluna = COLUNAS_EDITAVEIS[campo]
                if campo == "status":
                    sets.append(f"{coluna} = %s::status_lote")
                else:
                    sets.append(f"{coluna} = %s")
                params.append(valor)
            params.append(id_lote)
            cur.execute(f"UPDATE lote SET {', '.join(sets)} WHERE id_lote = %s", params)
            lote = _buscar(cur, id_lote)
        conn.commit()
    return lote