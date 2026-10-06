# conexão principal. E um erro ao gravar o log nunca derruba a requisição.
import ipaddress
from contextlib import closing, contextmanager
from typing import Optional

from fastapi import HTTPException, Request

from src import database


def _ip_do_cliente(request: Request) -> Optional[str]:
    # Não confia em X-Forwarded-For (pode ser forjado). Se a API ficar atrás de
    # proxy/load balancer, configure o uvicorn com --proxy-headers e --forwarded-allow-ips.
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def registrar(request: Request, acao: str, resultado: str = "sucesso",
              id_usuario: Optional[int] = None) -> None:
    try:
        with closing(database.conectar()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO log_acesso
                        (data_hora, acao, ip, resultado, fk_usuario_id_usuario)
                    VALUES (now() AT TIME ZONE 'UTC', %s, %s::inet, %s, %s)
                    """,
                    (acao[:150], _ip_do_cliente(request), resultado[:150], id_usuario),
                )
            conn.commit()
    except Exception as e:
        print(f"[ERRO] não foi possível gravar o log de auditoria: {e}")


class _Contexto:
    def __init__(self, acao: str, id_usuario: Optional[int]):
        self.acao = acao
        self.detalhe = ""
        self.id_usuario = id_usuario


@contextmanager
def auditar(request: Request, acao: str, id_usuario: Optional[int] = None):
    """Registra sucesso ou falha (HTTPException) do bloco.

    Dentro do bloco, o endpoint pode ajustar `ctx.detalhe` (ex.: "id=5") e
    `ctx.id_usuario` (quem executou a ação, quando for conhecido).
    Nunca passe senhas ou outros dados sensíveis para o log.
    """
    ctx = _Contexto(acao, id_usuario)
    try:
        yield ctx
    except HTTPException as exc:
        registrar(request, f"{ctx.acao} {ctx.detalhe}".strip(), f"falha: {exc.detail}", ctx.id_usuario)
        raise
    else:
        registrar(request, f"{ctx.acao} {ctx.detalhe}".strip(), "sucesso", ctx.id_usuario)