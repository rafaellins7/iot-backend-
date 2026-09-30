from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg2 import errors
from psycopg2.extras import RealDictCursor

from src.api.deps import get_conn
from src.api.schemas import (
    SenhaUpdate,
    StatusUsuario,
    UsuarioCreate,
    UsuarioOut,
    UsuarioUpdate,
)
from src.api.security import hash_senha, verificar_senha

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

SELECT_BASE = """
    SELECT u.id_usuario, u.nome, u.email, u.status, u.data_cadastro,
           u.fk_perfil_id_perfil AS id_perfil, p.nome AS perfil
    FROM usuario u
    LEFT JOIN perfil p ON p.id_perfil = u.fk_perfil_id_perfil
"""


def _buscar_usuario(cur, id_usuario: int) -> Optional[dict]:
    cur.execute(SELECT_BASE + " WHERE u.id_usuario = %s", (id_usuario,))
    return cur.fetchone()


def _perfil_existe(cur, id_perfil: int) -> bool:
    cur.execute("SELECT 1 FROM perfil WHERE id_perfil = %s", (id_perfil,))
    return cur.fetchone() is not None


def _email_em_uso(cur, email: str, ignorar_id: Optional[int] = None) -> bool:
    sql = "SELECT 1 FROM usuario WHERE lower(email) = lower(%s)"
    params = [email]
    if ignorar_id is not None:
        sql += " AND id_usuario <> %s"
        params.append(ignorar_id)
    cur.execute(sql, params)
    return cur.fetchone() is not None


def _ou_404(usuario):
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return usuario


@router.get("", response_model=List[UsuarioOut])
def listar_usuarios(status: Optional[StatusUsuario] = None, conn=Depends(get_conn)):
    sql = SELECT_BASE
    params = []
    if status is not None:
        sql += " WHERE u.status = %s"
        params.append(status.value)
    sql += " ORDER BY u.id_usuario"
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@router.get("/{id_usuario}", response_model=UsuarioOut)
def obter_usuario(id_usuario: int, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        return _ou_404(_buscar_usuario(cur, id_usuario))


@router.post("", response_model=UsuarioOut, status_code=201)
def criar_usuario(dados: UsuarioCreate, conn=Depends(get_conn)):
    email = dados.email.lower()
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if not _perfil_existe(cur, dados.id_perfil):
            raise HTTPException(status_code=400, detail="Perfil inexistente")
        if _email_em_uso(cur, email):
            raise HTTPException(status_code=409, detail="E-mail já cadastrado")
        try:
            cur.execute(
                """
                INSERT INTO usuario
                    (nome, email, senha, status, data_cadastro, fk_perfil_id_perfil)
                VALUES (%s, %s, %s, 'ativo', CURRENT_DATE, %s)
                RETURNING id_usuario
                """,
                (dados.nome, email, hash_senha(dados.senha), dados.id_perfil),
            )
        except errors.UniqueViolation:
            raise HTTPException(status_code=409, detail="E-mail já cadastrado")
        novo_id = cur.fetchone()["id_usuario"]
        usuario = _buscar_usuario(cur, novo_id)
    conn.commit()
    return usuario


@router.put("/{id_usuario}", response_model=UsuarioOut)
def editar_usuario(id_usuario: int, dados: UsuarioUpdate, conn=Depends(get_conn)):
    campos = dados.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        _ou_404(_buscar_usuario(cur, id_usuario))

        sets, params = [], []
        if "nome" in campos:
            sets.append("nome = %s")
            params.append(campos["nome"])
        if "email" in campos:
            email = campos["email"].lower()
            if _email_em_uso(cur, email, ignorar_id=id_usuario):
                raise HTTPException(status_code=409, detail="E-mail já cadastrado")
            sets.append("email = %s")
            params.append(email)
        if "id_perfil" in campos:
            if not _perfil_existe(cur, campos["id_perfil"]):
                raise HTTPException(status_code=400, detail="Perfil inexistente")
            sets.append("fk_perfil_id_perfil = %s")
            params.append(campos["id_perfil"])
        if "status" in campos:
            sets.append("status = %s")
            params.append(campos["status"].value)

        params.append(id_usuario)
        try:
            cur.execute(
                f"UPDATE usuario SET {', '.join(sets)} WHERE id_usuario = %s", params
            )
        except errors.UniqueViolation:
            raise HTTPException(status_code=409, detail="E-mail já cadastrado")
        usuario = _buscar_usuario(cur, id_usuario)
    conn.commit()
    return usuario


@router.delete("/{id_usuario}", status_code=204)
def desativar_usuario(id_usuario: int, conn=Depends(get_conn)):
    """Não apaga a linha: só muda o status para 'inativo'."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        _ou_404(_buscar_usuario(cur, id_usuario))
        cur.execute(
            "UPDATE usuario SET status = 'inativo' WHERE id_usuario = %s",
            (id_usuario,),
        )
    conn.commit()
    return Response(status_code=204)


@router.put("/{id_usuario}/senha", status_code=204)
def trocar_senha(id_usuario: int, dados: SenhaUpdate, conn=Depends(get_conn)):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT senha FROM usuario WHERE id_usuario = %s", (id_usuario,))
        linha = _ou_404(cur.fetchone())
        if not verificar_senha(dados.senha_atual, linha["senha"] or ""):
            raise HTTPException(status_code=403, detail="Senha atual incorreta")
        cur.execute(
            "UPDATE usuario SET senha = %s WHERE id_usuario = %s",
            (hash_senha(dados.senha_nova), id_usuario),
        )
    conn.commit()
    return Response(status_code=204)