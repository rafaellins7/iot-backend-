import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_conn
from src.database import get_db
from src.api.schemas import ParecerIAResponse
from src.api.services.ia_service import chamar_gemini_parecer, gerar_parecer_fallback

router = APIRouter(prefix="/ia", tags=["ia"])

class ModeloOut(BaseModel):
    id_modelo: int
    nome: str
    tipo_modelo: str
    finalidade: str
    algoritmo: Optional[str] = None
    versao: Optional[str] = None
    status: str
    data_criacao: Optional[str] = None
    data_atualizacao: Optional[str] = None


@router.get("/modelos", response_model=List[ModeloOut])
def listar_modelos(status: Optional[str] = None, conn=Depends(get_conn)):
    sql = "SELECT * FROM ia_modelo"
    args = ()
    if status:
        sql += " WHERE status = %s"
        args = (status,)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql + " ORDER BY id_modelo", args)
        linhas = cur.fetchall()
    for r in linhas:
        for k in ("data_criacao", "data_atualizacao"):
            r[k] = r[k].isoformat() if r[k] else None
    return linhas

@router.post("/parecer/gerar", response_model=ParecerIAResponse)
async def gerar_parecer_lote(
    id_lote: int,
    db: AsyncSession = Depends(get_db)
):
    agora = datetime.now(timezone.utc)

    # 1. Verificar Cache
    query_cache = text("""
        SELECT id, modelo, snapshot_entrada, conteudo_json, data_geracao 
        FROM parecer_ia 
        WHERE id_lote = :id_lote AND data_expiracao > :agora
        ORDER BY data_geracao DESC LIMIT 1
    """)
    res_cache = await db.execute(query_cache, {"id_lote": id_lote, "agora": agora})
    cache = res_cache.fetchone()

    if cache:
        return ParecerIAResponse(
            id_lote=id_lote,
            modelo=cache.modelo,
            origem="CACHE",
            conteudo=cache.conteudo_json,
            data_geracao=cache.data_geracao
        )

    # 2. Ler Métricas do Banco
    query_dados = text("""
        SELECT 
            coalesce(avg(l.vpd), 0) as vpd_medio,
            coalesce(avg(l.etc), 0) as etc_medio,
            coalesce(sum(l.horas_fora), 0) as horas_fora_da_faixa,
            coalesce(sum(l.prejuizo_brl), 0) as prejuizo_acumulado_brl,
            bool_or(l.is_simulado) as contem_dados_simulados
        FROM view_resumo_lote_leituras l
        WHERE l.id_lote = :id_lote
    """)
    res_dados = await db.execute(query_dados, {"id_lote": id_lote})
    dados_row = res_dados.fetchone()

    if not dados_row:
        raise HTTPException(status_code=404, detail="Lote não encontrado ou sem dados registrados.")

    snapshot_entrada = {
        "id_lote": id_lote,
        "vpd_medio": round(float(dados_row.vpd_medio), 2),
        "etc_medio": round(float(dados_row.etc_medio), 2),
        "horas_fora_da_faixa": int(dados_row.horas_fora_da_faixa),
        "prejuizo_acumulado_brl": round(float(dados_row.prejuizo_acumulado_brl), 2),
        "contem_dados_simulados": bool(dados_row.contem_dados_simulados)
    }

    # 3. LLM com Fallback
    origem = "GEMINI"
    try:
        conteudo_json, modelo_usado = await chamar_gemini_parecer(snapshot_entrada)
    except Exception as err:
        conteudo_json = gerar_parecer_fallback(snapshot_entrada)
        modelo_usado = "fallback-template"
        origem = "FALLBACK_TEMPLATE"

    # 4. Salvar Cache (1 Hora)
    expiracao = agora + timedelta(hours=1)
    query_salvar = text("""
        INSERT INTO parecer_ia (id_lote, modelo, snapshot_entrada, conteudo_json, data_geracao, data_expiracao)
        VALUES (:id_lote, :modelo, :snapshot, :conteudo, :agora, :expiracao)
    """)
    await db.execute(query_salvar, {
        "id_lote": id_lote,
        "modelo": modelo_usado,
        "snapshot": json.dumps(snapshot_entrada),
        "conteudo": json.dumps(conteudo_json),
        "agora": agora,
        "expiracao": expiracao
    })
    await db.commit()

    return ParecerIAResponse(
        id_lote=id_lote,
        modelo=modelo_usado,
        origem=origem,
        conteudo=conteudo_json,
        data_geracao=agora
    )