from datetime import timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from src.api.alerta_detalhe import JANELA_SERIE_HORAS, montar_detalhe
from src.api.deps import get_conn
from src.api.deps_auth import get_current_user
from src.api.escopo import filtrar_por_dono, id_dono

router = APIRouter(prefix="/alertas", tags=["alertas"])

# Sensor e lote do alerta vem pela leitura que o gerou (alerta preditivo: sem sensor/lote).
SELECT_BASE = """
    SELECT a.id_alerta, a.tipo_alerta, a.descricao, a.nivel::text AS nivel,
           a.status, a.data_hora,
           a.fk_leitura_id_leitura AS id_leitura,
           a.fk_previsao_id_previsao AS id_previsao,
           s.id_sensor, s.fk_lote_id_lote AS id_lote
    FROM alerta a
    LEFT JOIN leitura_climatica r ON r.id_leitura = a.fk_leitura_id_leitura
    LEFT JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
"""


class AlertaOut(BaseModel):
    id_alerta: int
    tipo_alerta: Optional[str] = None
    descricao: Optional[str] = None
    nivel: Optional[str] = None
    status: Optional[str] = None
    data_hora: Optional[str] = None   # ISO 8601 com Z (o banco guarda UTC sem fuso)
    id_leitura: Optional[int] = None
    id_previsao: Optional[int] = None
    id_sensor: Optional[int] = None
    id_lote: Optional[int] = None


class AlertaStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=50)


def _saida(linha: dict) -> dict:
    dt = linha.get("data_hora")
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        linha["data_hora"] = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return linha


@router.get("", response_model=List[AlertaOut])
def listar_alertas(
    status: Optional[str] = None,
    nivel: Optional[str] = None,
    id_sensor: Optional[int] = None,
    id_lote: Optional[int] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    where, params = [], []
    filtrar_por_dono(user, "s.fk_usuario_id_usuario", where, params)
    if status:
        where.append("lower(a.status) = lower(%s)")
        params.append(status)
    if nivel:
        where.append("a.nivel::text = %s")
        params.append(nivel)
    if id_sensor is not None:
        where.append("s.id_sensor = %s")
        params.append(id_sensor)
    if id_lote is not None:
        where.append("s.fk_lote_id_lote = %s")
        params.append(id_lote)
    sql = (SELECT_BASE
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY a.data_hora DESC, a.id_alerta DESC LIMIT %s OFFSET %s")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params + [limit, offset])
        return [_saida(r) for r in cur.fetchall()]


@router.post("/reconhecer-todos")
def reconhecer_todos(conn=Depends(get_conn), user=Depends(get_current_user)):
    """Move todos os alertas 'aberto' no escopo do usuário para 'reconhecido'."""
    dono = id_dono(user)
    with conn.cursor() as cur:
        if dono is None:
            cur.execute(
                "UPDATE alerta SET status = 'reconhecido' WHERE lower(status) = 'aberto'"
            )
        else:
            cur.execute(
                """
                UPDATE alerta a
                   SET status = 'reconhecido'
                 WHERE lower(a.status) = 'aberto'
                   AND (
                       a.fk_leitura_id_leitura IS NULL
                       OR EXISTS (
                           SELECT 1
                             FROM leitura_climatica r
                             JOIN sensor s ON s.id_sensor = r.fk_sensor_id_sensor
                            WHERE r.id_leitura = a.fk_leitura_id_leitura
                              AND s.fk_usuario_id_usuario = %s
                       )
                   )
                """,
                (dono,),
            )
        n = cur.rowcount
    conn.commit()
    return {"reconhecidos": n}


@router.get("/{id_alerta}", response_model=AlertaOut)
def obter_alerta(id_alerta: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(SELECT_BASE + " WHERE a.id_alerta = %s AND (%s::int IS NULL OR s.fk_usuario_id_usuario = %s)",
                    (id_alerta, id_dono(user), id_dono(user)))
        linha = cur.fetchone()
    if linha is None:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")
    return _saida(linha)


CONTEXTO_SQL = """
    SELECT s.id_sensor, s.nome AS sensor_nome, s.localizacao,
           s.ambiente::text AS ambiente, s.status::text AS sensor_status,
           l.id_lote, f.nome AS fruta, l.quantidade, l.unidade,
           fn_etapa_lote(l.status) AS etapa, l.destino, l.fk_fruta_id_fruta AS id_fruta
    FROM sensor s
    LEFT JOIN lote l ON l.id_lote = s.fk_lote_id_lote
    LEFT JOIN fruta f ON f.id_fruta = l.fk_fruta_id_fruta
    WHERE s.id_sensor = %s
"""


@router.get("/{id_alerta}/detalhe")
def detalhe_alerta(id_alerta: int, conn=Depends(get_conn), user=Depends(get_current_user)):
    """Dados para o card dinâmico: métricas vs. limites do lote, curva das últimas 2 h e contexto."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(SELECT_BASE + " WHERE a.id_alerta = %s AND (%s::int IS NULL OR s.fk_usuario_id_usuario = %s)",
                    (id_alerta, id_dono(user), id_dono(user)))
        linha = cur.fetchone()
        if linha is None:
            raise HTTPException(status_code=404, detail="Alerta não encontrado")
        alerta = _saida(dict(linha))

        contexto = limites = leitura_atual = leitura_gatilho = None
        serie = []

        if linha["id_sensor"] is not None:      # alerta preditivo não tem sensor
            cur.execute(CONTEXTO_SQL, (linha["id_sensor"],))
            contexto = cur.fetchone()

            # limites = config da fruta do lote na etapa atual do lote (campo/armazenamento/transporte)
            if contexto and contexto["id_fruta"] is not None and contexto["etapa"]:
                # mesma regra de fn_alerta_faixa: transporte cai em armazenamento se não houver faixa própria
                cur.execute(
                    """SELECT c.temp_min, c.temp_max, c.umidade_min, c.umidade_max
                         FROM config_parametro c
                        WHERE c.fk_fruta_id_fruta = %s
                          AND (c.etapa::text = %s
                               OR (%s = 'transporte' AND c.etapa::text = 'armazenamento'))
                        ORDER BY (c.etapa::text = %s) DESC
                        LIMIT 1""",
                    (contexto["id_fruta"], contexto["etapa"], contexto["etapa"], contexto["etapa"]),
                )
                limites = cur.fetchone()

            cur.execute(
                """SELECT id_leitura, temperatura, umidade, data_hora, origem
                     FROM leitura_climatica WHERE fk_sensor_id_sensor = %s
                    ORDER BY data_hora DESC, id_leitura DESC LIMIT 1""",
                (linha["id_sensor"],),
            )
            leitura_atual = cur.fetchone()

            if leitura_atual:
                # janela relativa à última leitura (e não a "agora"), para funcionar com dados de backfill
                cur.execute(
                    """SELECT temperatura, umidade, data_hora FROM leitura_climatica
                        WHERE fk_sensor_id_sensor = %s AND data_hora >= %s AND data_hora <= %s
                        ORDER BY data_hora ASC LIMIT 500""",
                    (linha["id_sensor"],
                     leitura_atual["data_hora"] - timedelta(hours=JANELA_SERIE_HORAS),
                     leitura_atual["data_hora"]),
                )
                serie = cur.fetchall()

        if linha["id_leitura"] is not None:
            cur.execute(
                "SELECT temperatura, umidade, data_hora FROM leitura_climatica WHERE id_leitura = %s",
                (linha["id_leitura"],),
            )
            leitura_gatilho = cur.fetchone()

    return montar_detalhe(alerta, contexto, limites, leitura_atual, serie, leitura_gatilho)


@router.patch("/{id_alerta}/status", response_model=AlertaOut)
def atualizar_status_alerta(
    id_alerta: int,
    dados: AlertaStatusUpdate,
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    dono = id_dono(user)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            SELECT_BASE + " WHERE a.id_alerta = %s AND (%s::int IS NULL OR s.fk_usuario_id_usuario = %s)",
            (id_alerta, dono, dono),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Alerta não encontrado")
        cur.execute(
            "UPDATE alerta SET status = %s WHERE id_alerta = %s RETURNING id_alerta",
            (dados.status.strip().lower(), id_alerta),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Alerta não encontrado")
        cur.execute(SELECT_BASE + " WHERE a.id_alerta = %s", (id_alerta,))
        linha = cur.fetchone()
    conn.commit()
    return _saida(linha)