from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg2.extras import RealDictCursor

from src.api.deps import get_conn
from src.api.schemas import LoteCreate, LoteResponse, LoteUpdate

router = APIRouter(prefix="/lotes", tags=["Lotes"])


@router.get("", response_model=List[LoteResponse])
def listar_lotes(
    status_filtro: Optional[str] = Query(None, alias="status"),
    skip: int = 0,
    limit: int = 100,
    conn=Depends(get_conn),
):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query = "SELECT id_lote, codigo, descricao, data_inicio, data_fim, status FROM lotes WHERE 1=1"
        params = []

        if status_filtro:
            query += " AND status = %s"
            params.append(status_filtro)

        query += " LIMIT %s OFFSET %s"
        params.extend([limit, skip])

        cur.execute(query, params)
        lotes = cur.fetchall()
        return lotes


@router.get("/{id_lote}", response_model=LoteResponse)
def obter_lote(id_lote: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query = "SELECT id_lote, codigo, descricao, data_inicio, data_fim, status FROM lotes WHERE id_lote = %s"
        cur.execute(query, (id_lote,))
        lote = cur.fetchone()

        if not lote:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lote não encontrado",
            )

        return lote


@router.post("", response_model=LoteResponse, status_code=status.HTTP_201_CREATED)
def criar_lote(lote: LoteCreate, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query = """
            INSERT INTO lotes (codigo, descricao, data_inicio, data_fim, status)
            VALUES (%(codigo)s, %(descricao)s, %(data_inicio)s, %(data_fim)s, %(status)s)
            RETURNING id_lote, codigo, descricao, data_inicio, data_fim, status
        """
        cur.execute(query, lote.dict())
        novo_lote = cur.fetchone()
        conn.commit()
        return novo_lote


@router.patch("/{id_lote}", response_model=LoteResponse)
def atualizar_lote(id_lote: int, lote_data: LoteUpdate, conn=Depends(get_conn)):
    dados = lote_data.dict(exclude_unset=True)
    if not dados:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sem dados para atualizar",
        )

    set_clauses = [f"{chave} = %({chave})s" for chave in dados.keys()]
    query = f"""
        UPDATE lotes
        SET {', '.join(set_clauses)}
        WHERE id_lote = %(id_lote)s
        RETURNING id_lote, codigo, descricao, data_inicio, data_fim, status
    """
    dados["id_lote"] = id_lote

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, dados)
        resultado = cur.fetchone()

        if not resultado:
            conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lote não encontrado",
            )

        conn.commit()
        return resultado