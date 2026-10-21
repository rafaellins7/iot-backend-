from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.database import get_db
from src.api.schemas import (
    AlertaPreditivoCreate,
    AlertaPreditivoOut,
    CorteAlertaPreditivo,
)

router = APIRouter(prefix="/alertas-preditivos", tags=["Alertas Preditivos"])


@router.get("/cortes", response_model=List[CorteAlertaPreditivo])
def obter_cortes_preditivos(db: Session = Depends(get_db)):
    query = """
        SELECT nivel, limiar_min, limiar_max, acao_recomendada
        FROM cortes_alerta_preditivo
        ORDER BY limiar_min ASC
    """
    result = db.execute(query).fetchall()
    return [dict(row._mapping) for row in result]


@router.get("", response_model=List[AlertaPreditivoOut])
def listar_alertas_preditivos(
    id_lote: Optional[int] = None,
    id_sensor: Optional[int] = None,
    nivel_severidade: Optional[str] = Query(None, alias="nivel"),
    status_filtro: Optional[str] = Query(None, alias="status"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = """
        SELECT id_alerta_preditivo, id_sensor, id_lote, probabilidade_risco,
               nivel_severidade, mensagem, previsao_data_hora, status, data_geracao
        FROM alertas_preditivos
        WHERE 1=1
    """
    params = {}

    if id_lote:
        query += " AND id_lote = :id_lote"
        params["id_lote"] = id_lote

    if id_sensor:
        query += " AND id_sensor = :id_sensor"
        params["id_sensor"] = id_sensor

    if nivel_severidade:
        query += " AND nivel_severidade = :nivel"
        params["nivel"] = nivel_severidade

    if status_filtro:
        query += " AND status = :status"
        params["status"] = status_filtro

    query += " ORDER BY data_geracao DESC LIMIT :limit OFFSET :skip"
    params["limit"] = limit
    params["skip"] = skip

    result = db.execute(query, params).fetchall()
    return [dict(row._mapping) for row in result]


@router.post("", response_model=AlertaPreditivoOut, status_code=status.HTTP_201_CREATED)
def criar_alerta_preditivo(
    payload: AlertaPreditivoCreate, db: Session = Depends(get_db)
):
    query = """
        INSERT INTO alertas_preditivos (
            id_sensor, id_lote, probabilidade_risco, nivel_severidade, mensagem, previsao_data_hora, status
        ) VALUES (
            :id_sensor, :id_lote, :probabilidade_risco, :nivel_severidade, :mensagem, :previsao_data_hora, :status
        )
        RETURNING id_alerta_preditivo, id_sensor, id_lote, probabilidade_risco,
                  nivel_severidade, mensagem, previsao_data_hora, status, data_geracao
    """
    novo = db.execute(query, payload.model_dump()).fetchone()
    db.commit()
    return dict(novo._mapping)


@router.patch("/{id_alerta_preditivo}/status", response_model=AlertaPreditivoOut)
def atualizar_status_alerta_preditivo(
    id_alerta_preditivo: int, status_novo: str, db: Session = Depends(get_db)
):
    query = """
        UPDATE alertas_preditivos
        SET status = :status
        WHERE id_alerta_preditivo = :id
        RETURNING id_alerta_preditivo, id_sensor, id_lote, probabilidade_risco,
                  nivel_severidade, mensagem, previsao_data_hora, status, data_geracao
    """
    resultado = db.execute(query, {"status": status_novo, "id": id_alerta_preditivo}).fetchone()

    if not resultado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta preditivo não encontrado",
        )

    db.commit()
    return dict(resultado._mapping)