from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg2 import errors
from psycopg2.extras import RealDictCursor

from src.api.auditoria import auditar
from src.api.deps import get_conn
from src.api.schemas import SensorCreate, SensorOut, SensorUpdate

router = APIRouter(prefix="/sensores", tags=["sensores"])

SELECT_BASE = """
    SELECT s.id_sensor, s.nome, s.tipo_sensor, s.localizacao, s.channel_id,
           s.status::text AS status, s.fk_lote_id_lote AS id_lote, s.ambiente,
           u.data_hora AS ultima_leitura, u.temperatura, u.umidade, u.origem
    FROM sensor s
    LEFT JOIN LATERAL (
        SELECT l.data_hora, l.temperatura, l.umidade, l.origem
        FROM leitura_climatica l
        WHERE l.fk_sensor_id_sensor = s.id_sensor
        ORDER BY l.data_hora DESC, l.id_leitura DESC
        LIMIT 1
    ) u ON true
"""

# campo da API -> coluna do banco (só estes nomes entram no UPDATE)
COLUNAS_EDITAVEIS = {
    "nome": "nome",
    "tipo_sensor": "tipo_sensor",
    "localizacao": "localizacao",
    "channel_id": "channel_id",
    "id_lote": "fk_lote_id_lote",
    "ambiente": "ambiente",
    "status": "status",
}
NAO_PODE_SER_NULO = ("nome", "ambiente", "status")


def _buscar_sensor(cur, id_sensor: int) -> Optional[dict]:
    cur.execute(SELECT_BASE + " WHERE s.id_sensor = %s", (id_sensor,))
    return cur.fetchone()


def _ou_404(sensor):
    if sensor is None:
        raise HTTPException(status_code=404, detail="Sensor não encontrado")
    return sensor


def _lote_existe(cur, id_lote: int) -> bool:
    cur.execute("SELECT 1 FROM lote WHERE id_lote = %s", (id_lote,))
    return cur.fetchone() is not None


def _channel_em_uso(cur, channel_id: int, ignorar_id: Optional[int] = None) -> bool:
    sql = "SELECT 1 FROM sensor WHERE channel_id = %s"
    params = [channel_id]
    if ignorar_id is not None:
        sql += " AND id_sensor <> %s"
        params.append(ignorar_id)
    cur.execute(sql, params)
    return cur.fetchone() is not None


@router.get("", response_model=List[SensorOut])
def listar_sensores(
    ambiente: Optional[str] = None,
    id_lote: Optional[int] = None,
    status: Optional[str] = None,
    conn=Depends(get_conn),
):
    where, params = [], []
    if ambiente:
        where.append("s.ambiente = %s")
        params.append(ambiente)
    if id_lote is not None:
        where.append("s.fk_lote_id_lote = %s")
        params.append(id_lote)
    if status:
        where.append("s.status::text = %s")
        params.append(status)
    sql = SELECT_BASE + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY s.id_sensor"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@router.get("/{id_sensor}", response_model=SensorOut)
def obter_sensor(id_sensor: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        return _ou_404(_buscar_sensor(cur, id_sensor))


@router.post("", response_model=SensorOut, status_code=201)
def criar_sensor(dados: SensorCreate, request: Request, conn=Depends(get_conn)):
    with auditar(request, "criar_sensor") as ctx:
        ctx.detalhe = f"nome={dados.nome}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if dados.id_lote is not None and not _lote_existe(cur, dados.id_lote):
                raise HTTPException(status_code=400, detail="Lote inexistente")
            if dados.channel_id is not None and _channel_em_uso(cur, dados.channel_id):
                raise HTTPException(status_code=409, detail="channel_id já cadastrado")
            try:
                cur.execute(
                    """
                    INSERT INTO sensor
                        (nome, tipo_sensor, localizacao, channel_id, status,
                         fk_lote_id_lote, ambiente)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id_sensor
                    """,
                    (
                        dados.nome, dados.tipo_sensor, dados.localizacao,
                        dados.channel_id, dados.status.value, dados.id_lote,
                        dados.ambiente.value,
                    ),
                )
            except errors.UniqueViolation:
                raise HTTPException(status_code=409, detail="channel_id já cadastrado")
            novo_id = cur.fetchone()["id_sensor"]
            sensor = _buscar_sensor(cur, novo_id)
        conn.commit()
        ctx.detalhe = f"id={novo_id} nome={dados.nome}"
    return sensor


@router.put("/{id_sensor}", response_model=SensorOut)
def editar_sensor(id_sensor: int, dados: SensorUpdate, request: Request, conn=Depends(get_conn)):
    campos = dados.model_dump(exclude_unset=True)
    with auditar(request, "editar_sensor") as ctx:
        ctx.detalhe = f"id={id_sensor} campos={','.join(sorted(campos))}"
        if not campos:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
        for nome in NAO_PODE_SER_NULO:
            if nome in campos and campos[nome] is None:
                raise HTTPException(status_code=400, detail=f"'{nome}' não pode ser nulo")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ou_404(_buscar_sensor(cur, id_sensor))

            if campos.get("id_lote") is not None and not _lote_existe(cur, campos["id_lote"]):
                raise HTTPException(status_code=400, detail="Lote inexistente")
            if campos.get("channel_id") is not None and _channel_em_uso(
                cur, campos["channel_id"], ignorar_id=id_sensor
            ):
                raise HTTPException(status_code=409, detail="channel_id já cadastrado")

            sets, params = [], []
            for campo, valor in campos.items():
                if isinstance(valor, Enum):
                    valor = valor.value
                sets.append(f"{COLUNAS_EDITAVEIS[campo]} = %s")
                params.append(valor)
            params.append(id_sensor)
            try:
                cur.execute(f"UPDATE sensor SET {', '.join(sets)} WHERE id_sensor = %s", params)
            except errors.UniqueViolation:
                raise HTTPException(status_code=409, detail="channel_id já cadastrado")
            sensor = _buscar_sensor(cur, id_sensor)
        conn.commit()
    return sensor


@router.delete("/{id_sensor}", status_code=204)
def desativar_sensor(id_sensor: int, request: Request, conn=Depends(get_conn)):
    """Não apaga a linha: só muda o status para 'inativo'."""
    with auditar(request, "desativar_sensor") as ctx:
        ctx.detalhe = f"id={id_sensor}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ou_404(_buscar_sensor(cur, id_sensor))
            cur.execute("UPDATE sensor SET status = 'inativo' WHERE id_sensor = %s", (id_sensor,))
        conn.commit()
    return Response(status_code=204)