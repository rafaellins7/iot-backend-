from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.database import get_db
from src.api.schemas import LoteCreate, LoteResponse, LoteUpdate

router = APIRouter(prefix="/lotes", tags=["Lotes"])

@router.get("", response_model=List[LoteResponse])
def listar_lotes(
    status_filtro: Optional[str] = Query(None, alias="status"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    query = "SELECT id_lote, codigo, descricao, data_inicio, data_fim, status FROM lotes WHERE 1=1"
    params = {}

    if status_filtro:
        query += " AND status = :status"
        params["status"] = status_filtro

    query += " LIMIT :limit OFFSET :skip"
    params["limit"] = limit
    params["skip"] = skip

    result = db.execute(query, params).fetchall()
    return [dict(row._mapping) for row in result]

@router.get("/{id_lote}", response_model=LoteResponse)
def obter_lote(id_lote: int, db: Session = Depends(get_db)):
    query = "SELECT id_lote, codigo, descricao, data_inicio, data_fim, status FROM lotes WHERE id_lote = :id"
    row = db.execute(query, {"id": id_lote}).fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote não encontrado")

    return dict(row._mapping)

@router.post("", response_model=LoteResponse, status_code=status.HTTP_201_CREATED)
def criar_lote(lote: LoteCreate, db: Session = Depends(get_db)):
    query = """
        INSERT INTO lotes (codigo, descricao, data_inicio, data_fim, status)
        VALUES (:codigo, :descricao, :data_inicio, :data_fim, :status)
        RETURNING id_lote, codigo, descricao, data_inicio, data_fim, status
    """
    novo_lote = db.execute(query, lote.dict()).fetchone()
    db.commit()
    return dict(novo_lote._mapping)

@router.patch("/{id_lote}", response_model=LoteResponse)
def atualizar_lote(id_lote: int, lote_data: LoteUpdate, db: Session = Depends(get_db)):
    dados = lote_data.dict(exclude_unset=True)
    if not dados:
        raise HTTPException(status_code=400, detail="Sem dados para atualizar")

    set_clauses = [f"{chave} = :{chave}" for chave in dados.keys()]
    query = f"""
        UPDATE lotes
        SET {', '.join(set_clauses)}
        WHERE id_lote = :id_lote
        RETURNING id_lote, codigo, descricao, data_inicio, data_fim, status
    """
    dados["id_lote"] = id_lote
    resultado = db.execute(query, dados).fetchone()

    if not resultado:
        raise HTTPException(status_code=404, detail="Lote não encontrado")

    db.commit()
    return dict(resultado._mapping)