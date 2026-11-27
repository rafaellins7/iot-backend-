"""TOTP (RFC 6238): segredo, QR Code, verificação e códigos de recuperação. Sem acesso a banco."""
import base64
import hashlib
import hmac
import io
import os
import secrets
import time

import pyotp
import qrcode
from cryptography.fernet import Fernet

EMISSOR = "Raiz"
PERIODO_S = 30        # um código muda a cada 30 s
DIGITOS = 6
JANELA = 1            # aceita o passo atual e 1 para cada lado (±30 s de relógio dessincronizado)
N_RECUPERACAO = 10
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sem 0/O/1/I


def _fernet() -> Fernet:
    return Fernet(os.environ["TOTP_ENC_KEY"].encode())


def novo_segredo() -> str:
    return pyotp.random_base32()


def cifrar(segredo: str) -> str:
    return _fernet().encrypt(segredo.encode()).decode()


def decifrar(cifrado: str) -> str:
    return _fernet().decrypt(cifrado.encode()).decode()


def uri_otpauth(segredo: str, email: str) -> str:
    return pyotp.TOTP(segredo, digits=DIGITOS, interval=PERIODO_S).provisioning_uri(name=email, issuer_name=EMISSOR)


def qr_png_base64(uri: str) -> str:
    buf = io.BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def passo_atual(agora: float | None = None) -> int:
    return int((time.time() if agora is None else agora) // PERIODO_S)


def codigo_no_passo(segredo: str, passo: int) -> str:
    return pyotp.TOTP(segredo, digits=DIGITOS, interval=PERIODO_S).at(passo * PERIODO_S)


def formato_totp(codigo: str) -> bool:
    return len(codigo) == DIGITOS and codigo.isascii() and codigo.isdigit()


def verificar(segredo: str, codigo: str, ultimo_passo: int | None, agora: float | None = None) -> int | None:
    """Devolve o time-step aceito, ou None se o código for errado, vencido ou já usado.

    Reuso: só vale passo MAIOR que `ultimo_passo` (o chamador grava o passo aceito).
    """
    if not formato_totp(codigo):
        return None
    atual = passo_atual(agora)
    achado = None
    for passo in range(atual - JANELA, atual + JANELA + 1):    # percorre todos: tempo não depende de qual acertou
        if hmac.compare_digest(codigo_no_passo(segredo, passo), codigo):
            achado = passo
    if achado is None or (ultimo_passo is not None and achado <= ultimo_passo):
        return None
    return achado


# ---------- códigos de recuperação ----------
def gerar_codigos_recuperacao(n: int = N_RECUPERACAO) -> list[str]:
    cods = []
    for _ in range(n):
        c = "".join(secrets.choice(ALFABETO) for _ in range(10))
        cods.append(f"{c[:5]}-{c[5:]}")
    return cods


def normalizar_recuperacao(codigo: str) -> str:
    return codigo.replace("-", "").replace(" ", "").upper()


def hash_recuperacao(id_usuario: int, codigo: str) -> str:
    msg = f"rec:{id_usuario}:{normalizar_recuperacao(codigo)}".encode()
    return hmac.new(os.environ["EMAIL_OTP_KEY"].encode(), msg, hashlib.sha256).hexdigest()
