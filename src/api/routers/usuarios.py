from typing import List, Optional

import secrets
from fastapi import BackgroundTasks
from src.api.services.ativacao import emitir_ativacao

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg2 import errors
from psycopg2.extras import RealDictCursor

from src.api.auditoria import auditar
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
def criar_usuario(dados: UsuarioCreate, request: Request, background: BackgroundTasks, conn=Depends(get_conn)):
    email = dados.email.lower()
    with auditar(request, "criar_usuario") as ctx:
        ctx.detalhe = f"email={email}"
        if dados.senha:
            status_ini, senha_hash, trocar = "ativo", hash_senha(dados.senha), True
        else:
            status_ini, senha_hash, trocar = "pendente", hash_senha(secrets.token_urlsafe(32)), False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            perfil_id = dados.id_perfil or dados.fk_perfil_id_perfil or 1
            if not _perfil_existe(cur, perfil_id):
                raise HTTPException(status_code=400, detail="Perfil inexistente")
            if _email_em_uso(cur, email):
                raise HTTPException(status_code=409, detail="E-mail já cadastrado")
            try:
                cur.execute(
                    """
                    INSERT INTO usuario
                        (nome, email, senha, status, data_cadastro, fk_perfil_id_perfil, deve_trocar_senha, ativado_em)
                    VALUES (%s, %s, %s, %s, CURRENT_DATE, %s, %s, CASE WHEN %s THEN now() END)
                    RETURNING id_usuario
                    """,
                    (dados.nome, email, senha_hash, status_ini, perfil_id, trocar, status_ini == "ativo"),
                )
            except errors.UniqueViolation:
                raise HTTPException(status_code=409, detail="E-mail já cadastrado")
            novo_id = cur.fetchone()["id_usuario"]
            if status_ini == "pendente":
                emitir_ativacao(
                    conn, {"id_usuario": novo_id, "nome": dados.nome, "email": email},
                    request.client.host if request.client else None, background,
                )
            usuario = _buscar_usuario(cur, novo_id)
        conn.commit()
        ctx.detalhe = f"id={novo_id} email={email} status={status_ini}"
    return usuario


@router.put("/{id_usuario}", response_model=UsuarioOut)
def editar_usuario(id_usuario: int, dados: UsuarioUpdate, request: Request, conn=Depends(get_conn)):
    campos = dados.model_dump(exclude_unset=True)
    with auditar(request, "editar_usuario") as ctx:
        ctx.detalhe = f"id={id_usuario} campos={','.join(sorted(campos))}"
        if not campos:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            atual = _ou_404(_buscar_usuario(cur, id_usuario))

            sets, params = [], []
            if "nome" in campos and campos["nome"]:
                sets.append("nome = %s")
                params.append(campos["nome"])
            if "email" in campos and campos["email"]:
                email = campos["email"].lower()
                if _email_em_uso(cur, email, ignorar_id=id_usuario):
                    raise HTTPException(status_code=409, detail="E-mail já cadastrado")
                sets.append("email = %s")
                params.append(email)
            id_perfil = campos.get("id_perfil") or campos.get("fk_perfil_id_perfil")
            if id_perfil is not None:
                if not _perfil_existe(cur, id_perfil):
                    raise HTTPException(status_code=400, detail="Perfil inexistente")
                sets.append("fk_perfil_id_perfil = %s")
                params.append(id_perfil)
            if "status" in campos and campos["status"] is not None:
                novo = campos["status"]
                novo_valor = novo.value if hasattr(novo, "value") else str(novo)
                if novo_valor == "pendente" or (novo_valor == "ativo" and atual["status"] == "pendente"):
                    raise HTTPException(status_code=400, detail="Usuário pendente só é ativado pelo código de ativação")
                sets.append("status = %s")
                params.append(novo_valor)

            if not sets:
                return atual

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
def desativar_usuario(id_usuario: int, request: Request, conn=Depends(get_conn)):
    """Não apaga a linha: só muda o status para 'inativo'."""
    with auditar(request, "desativar_usuario") as ctx:
        ctx.detalhe = f"id={id_usuario}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ou_404(_buscar_usuario(cur, id_usuario))
            cur.execute(
                "UPDATE usuario SET status = 'inativo' WHERE id_usuario = %s",
                (id_usuario,),
            )
        conn.commit()
    return Response(status_code=204)


@router.post("/{id_usuario}/reenviar-ativacao", status_code=204)
def reenviar_ativacao(id_usuario: int, request: Request, background: BackgroundTasks, conn=Depends(get_conn)):
    with auditar(request, "reenviar_ativacao") as ctx:
        ctx.detalhe = f"id={id_usuario}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            u = _ou_404(_buscar_usuario(cur, id_usuario))
        if u["status"] != "pendente":
            raise HTTPException(status_code=409, detail="Usuário não está pendente de ativação")
        emitir_ativacao(conn, u, request.client.host if request.client else None, background)
        conn.commit()
    return Response(status_code=204)


@router.put("/{id_usuario}/senha", status_code=204)
def trocar_senha(id_usuario: int, dados: SenhaUpdate, request: Request, conn=Depends(get_conn)):
    with auditar(request, "trocar_senha") as ctx:
        ctx.detalhe = f"id={id_usuario}"
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT senha FROM usuario WHERE id_usuario = %s", (id_usuario,))
            linha = _ou_404(cur.fetchone())
            ctx.id_usuario = id_usuario
            if not verificar_senha(dados.senha_atual, linha["senha"] or ""):
                raise HTTPException(status_code=403, detail="Senha atual incorreta")
            cur.execute(
                "UPDATE usuario SET senha = %s WHERE id_usuario = %s",
                (hash_senha(dados.senha_nova), id_usuario),
            )
        conn.commit()
    return Response(status_code=204)