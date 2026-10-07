from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.database import get_db
from src.api.schemas import AlertaResponse, AlertaUpdateStatus

router = APIRouter(prefix="/alertas", tags=["Alertas"])

@router.get("", response_model=List[AlertaResponse])
def listar_alertas(
    status_filtro: Optional[str] = Query(None, alias="status"),
    nivel_severidade: Optional[str] = Query(None),
    id_sensor: Optional[int] = None,
    id_lote: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    query = """
        SELECT id_alerta, id_sensor, id_lote, mensagem, nivel_severidade, status, data_criacao, data_resolucao
        FROM alertas
        WHERE 1=1
    """
    params = {}

    if status_filtro:
        query += " AND status = :status"
        params["status"] = status_filtro

    if nivel_severidade:
        query += " AND nivel_severidade = :nivel"
        params["nivel"] = nivel_severidade

    if id_sensor:
        query += " AND id_sensor = :id_sensor"
        params["id_sensor"] = id_sensor

    if id_lote:
        query += " AND id_lote = :id_lote"
        params["id_lote"] = id_lote

    query += " ORDER BY data_criacao DESC LIMIT :limit OFFSET :skip"
    params["limit"] = limit
    params["skip"] = skip

    result = db.execute(query, params).fetchall()
    return [dict(row._mapping) for row in result]

@router.get("/{id_alerta}", response_model=AlertaResponse)
def obter_alerta(id_alerta: int, db: Session = Depends(get_db)):
    query = """
        SELECT id_alerta, id_sensor, id_lote, mensagem, nivel_severidade, status, data_criacao, data_resolucao
        FROM alertas
        WHERE id_alerta = :id
    """
    row = db.execute(query, {"id": id_alerta}).fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta não encontrado")

    return dict(row._mapping)

@router.patch("/{id_alerta}/status", response_model=AlertaResponse)
def atualizar_status_alerta(
    id_alerta: int, 
    payload: AlertaUpdateStatus, 
    db: Session = Depends(get_db)
):
    data_resolucao = datetime.now() if payload.status == "RESOLVIDO" else None

    query = """
        UPDATE alertas
        SET status = :status,
            data_resolucao = COALESCE(:data_resolucao, data_resolucao)
        WHERE id_alerta = :id_alerta
        RETURNING id_alerta, id_sensor, id_lote, mensagem, nivel_severidade, status, data_criacao, data_resolucao
    """
    
    params = {
        "status": payload.status,
        "data_resolucao": data_resolucao,
        "id_alerta": id_alerta
    }
    
    resultado = db.execute(query, params).fetchone()

    if not resultado:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta não encontrado")

    db.commit()
    return dict(resultado._mapping)