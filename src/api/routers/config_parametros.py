from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2 import errors
from psycopg2.extras import RealDictCursor

from src.api.auditoria import auditar
from src.api.deps import get_conn
from src.api.schemas import ConfigParametroCreate, ConfigParametroOut, ConfigParametroUpdate

router = APIRouter(prefix="/config-parametros", tags=["config-parametros"])

SELECT_BASE = """
    SELECT c.id_config, c.fk_fruta_id_fruta AS id_fruta, f.nome AS fruta, c.etapa,
           c.temp_min, c.temp_max, c.umidade_min, c.umidade_max
    FROM config_parametro c
    LEFT JOIN fruta f ON f.id_fruta = c.fk_fruta_id_fruta
"""

# campo da API -> coluna do banco (só estes nomes entram no UPDATE)
COLUNAS_EDITAVEIS = {
    "id_fruta": "fk_fruta_id_fruta",
    "etapa": "etapa",
    "temp_min": "temp_min",
    "temp_max": "temp_max",
    "umidade_min": "umidade_min",
    "umidade_max": "umidade_max",
}


def _buscar_config(cur, id_config: int) -> Optional[dict]:
    cur.execute(SELECT_BASE + " WHERE c.id_config = %s", (id_config,))
    return cur.fetchone()


def _ou_404(config):
    if config is None:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")
    return config


def _fruta_existe(cur, id_fruta: int) -> bool:
    cur.execute("SELECT 1 FROM fruta WHERE id_fruta = %s", (id_fruta,))
    return cur.fetchone() is not None


def _combinacao_em_uso(cur, id_fruta: int, etapa: str, ignorar_id: Optional[int] = None) -> bool:
    sql = "SELECT 1 FROM config_parametro WHERE fk_fruta_id_fruta = %s AND etapa = %s"
    params = [id_fruta, etapa]
    if ignorar_id is not None:
        sql += " AND id_config <> %s"
        params.append(ignorar_id)
    cur.execute(sql, params)
    return cur.fetchone() is not None


def _validar_faixas(temp_min, temp_max, umidade_min, umidade_max) -> None:
    if temp_min >= temp_max:
        raise HTTPException(status_code=400, detail="temp_min deve ser menor que temp_max")
    if umidade_min >= umidade_max:
        raise HTTPException(status_code=400, detail="umidade_min deve ser menor que umidade_max")


@router.get("", response_model=List[ConfigParametroOut])
def listar_config(
    id_fruta: Optional[int] = None,
    etapa: Optional[str] = None,
    conn=Depends(get_conn),
):
    where, params = [], []
    if id_fruta is not None:
        where.append("c.fk_fruta_id_fruta = %s")
        params.append(id_fruta)
    if etapa:
        where.append("c.etapa = %s")
        params.append(etapa)
    sql = SELECT_BASE + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY f.nome, c.etapa"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@router.get("/{id_config}", response_model=ConfigParametroOut)
def obter_config(id_config: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        return _ou_404(_buscar_config(cur, id_config))


@router.post("", response_model=ConfigParametroOut, status_code=201)
def criar_config(dados: ConfigParametroCreate, request: Request, conn=Depends(get_conn)):
    with auditar(request, "criar_config_parametro") as ctx:
        ctx.detalhe = f"fruta={dados.id_fruta} etapa={dados.etapa.value}"
        _validar_faixas(dados.temp_min, dados.temp_max, dados.umidade_min, dados.umidade_max)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not _fruta_existe(cur, dados.id_fruta):
                raise HTTPException(status_code=400, detail="Fruta inexistente")
            if _combinacao_em_uso(cur, dados.id_fruta, dados.etapa.value):
                raise HTTPException(status_code=409, detail="Já existe faixa para esta fruta e etapa")
            try:
                cur.execute(
                    """
                    INSERT INTO config_parametro
                        (fk_fruta_id_fruta, etapa, temp_min, temp_max, umidade_min, umidade_max)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id_config
                    """,
                    (dados.id_fruta, dados.etapa.value, dados.temp_min, dados.temp_max,
                     dados.umidade_min, dados.umidade_max),
                )
            except errors.UniqueViolation:
                raise HTTPException(status_code=409, detail="Já existe faixa para esta fruta e etapa")
            novo_id = cur.fetchone()["id_config"]
            config = _buscar_config(cur, novo_id)
        conn.commit()
        ctx.detalhe = f"id={novo_id} fruta={dados.id_fruta} etapa={dados.etapa.value}"
    return config


@router.put("/{id_config}", response_model=ConfigParametroOut)
def editar_config(id_config: int, dados: ConfigParametroUpdate, request: Request, conn=Depends(get_conn)):
    campos = dados.model_dump(exclude_unset=True)
    with auditar(request, "editar_config_parametro") as ctx:
        ctx.detalhe = f"id={id_config} campos={','.join(sorted(campos))}"
        if not campos:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
        for nome, valor in campos.items():
            if valor is None:
                raise HTTPException(status_code=400, detail=f"'{nome}' não pode ser nulo")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            atual = _ou_404(_buscar_config(cur, id_config))

            # valores finais = o que já existe + o que o cliente mandou
            final = {k: atual[k] for k in COLUNAS_EDITAVEIS}
            final.update({k: (v.value if isinstance(v, Enum) else v) for k, v in campos.items()})

            _validar_faixas(final["temp_min"], final["temp_max"],
                            final["umidade_min"], final["umidade_max"])
            if "id_fruta" in campos and not _fruta_existe(cur, final["id_fruta"]):
                raise HTTPException(status_code=400, detail="Fruta inexistente")
            if ("id_fruta" in campos or "etapa" in campos) and _combinacao_em_uso(
                cur, final["id_fruta"], final["etapa"], ignorar_id=id_config
            ):
                raise HTTPException(status_code=409, detail="Já existe faixa para esta fruta e etapa")

            sets, params = [], []
            for campo in campos:
                sets.append(f"{COLUNAS_EDITAVEIS[campo]} = %s")
                params.append(final[campo])
            params.append(id_config)
            try:
                cur.execute(f"UPDATE config_parametro SET {', '.join(sets)} WHERE id_config = %s", params)
            except errors.UniqueViolation:
                raise HTTPException(status_code=409, detail="Já existe faixa para esta fruta e etapa")
            config = _buscar_config(cur, id_config)
        conn.commit()
    return config