"""Persistência do TOTP. O chamador faz o commit."""
from psycopg2.extras import RealDictCursor

from . import totp


def obter(conn, id_usuario: int, travar: bool = False) -> dict | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT segredo_cifrado, confirmado_em, ultimo_passo FROM totp_segredo "
            "WHERE fk_usuario_id_usuario = %s" + (" FOR UPDATE" if travar else ""),
            (id_usuario,),
        )
        return cur.fetchone()


def tem_totp_ativo(conn, id_usuario: int) -> bool:
    row = obter(conn, id_usuario)
    return bool(row and row["confirmado_em"])


def iniciar_cadastro(conn, id_usuario: int, segredo: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO totp_segredo (fk_usuario_id_usuario, segredo_cifrado, criado_em, confirmado_em, ultimo_passo)
            VALUES (%s, %s, now(), NULL, NULL)
            ON CONFLICT (fk_usuario_id_usuario) DO UPDATE
               SET segredo_cifrado = EXCLUDED.segredo_cifrado, criado_em = now(),
                   confirmado_em = NULL, ultimo_passo = NULL
            """,
            (id_usuario, totp.cifrar(segredo)),
        )


def confirmar_cadastro(conn, id_usuario: int, codigo: str) -> list[str] | None:
    """Valida o 1º código; se certo, ativa o TOTP e devolve os códigos de recuperação (única vez)."""
    row = obter(conn, id_usuario, travar=True)
    if not row or row["confirmado_em"]:
        return None
    passo = totp.verificar(totp.decifrar(row["segredo_cifrado"]), codigo.strip(), None)
    if passo is None:
        return None
    with conn.cursor() as cur:
        cur.execute("UPDATE totp_segredo SET confirmado_em = now(), ultimo_passo = %s WHERE fk_usuario_id_usuario = %s",
                    (passo, id_usuario))
    return regenerar_recuperacao(conn, id_usuario)


def regenerar_recuperacao(conn, id_usuario: int) -> list[str]:
    """Apaga TODOS os códigos antigos (usados ou não) e cria um conjunto novo."""
    codigos = totp.gerar_codigos_recuperacao()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM totp_recuperacao WHERE fk_usuario_id_usuario = %s", (id_usuario,))
        for c in codigos:
            cur.execute("INSERT INTO totp_recuperacao (fk_usuario_id_usuario, codigo_hash) VALUES (%s, %s)",
                        (id_usuario, totp.hash_recuperacao(id_usuario, c)))
    return codigos


def restantes_recuperacao(conn, id_usuario: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM totp_recuperacao WHERE fk_usuario_id_usuario = %s AND usado_em IS NULL",
                    (id_usuario,))
        return cur.fetchone()[0]


def verificar_e_consumir(conn, id_usuario: int, codigo: str, aceitar_recuperacao: bool = True) -> str | None:
    """'totp' | 'recuperacao' | None. Um código TOTP só vale uma vez; um de recuperação também.

    A linha do usuário fica travada (FOR UPDATE): duas requisições simultâneas com o mesmo código
    não passam as duas.
    """
    row = obter(conn, id_usuario, travar=True)
    if not row or not row["confirmado_em"]:
        return None
    codigo = codigo.strip()
    if totp.formato_totp(codigo):
        passo = totp.verificar(totp.decifrar(row["segredo_cifrado"]), codigo, row["ultimo_passo"])
        if passo is None:
            return None
        with conn.cursor() as cur:
            cur.execute("UPDATE totp_segredo SET ultimo_passo = %s WHERE fk_usuario_id_usuario = %s", (passo, id_usuario))
        return "totp"
    if not aceitar_recuperacao or not codigo:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE totp_recuperacao SET usado_em = now() "
            "WHERE fk_usuario_id_usuario = %s AND codigo_hash = %s AND usado_em IS NULL RETURNING id_recuperacao",
            (id_usuario, totp.hash_recuperacao(id_usuario, codigo)),
        )
        return "recuperacao" if cur.fetchone() else None


def desativar(conn, id_usuario: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM totp_recuperacao WHERE fk_usuario_id_usuario = %s", (id_usuario,))
        cur.execute("DELETE FROM totp_segredo WHERE fk_usuario_id_usuario = %s", (id_usuario,))
