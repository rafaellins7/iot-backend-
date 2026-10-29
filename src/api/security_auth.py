import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, status

JWT_SECRET = os.environ["JWT_SECRET"]
EMAIL_OTP_KEY = os.environ["EMAIL_OTP_KEY"]
JWT_ALG = "HS256"
ACCESS_MIN = 15      # JWT de acesso
PENDING_MIN = 10     # token temporário do passo 1 (>= validade do código por e-mail)
REFRESH_DIAS = 7

_ph = PasswordHasher()  # argon2id com parâmetros padrão

# hash falso para gastar o mesmo tempo quando o e-mail não existe (evita enumeração de usuários)
DUMMY_HASH = _ph.hash("senha-falsa-tempo-constante")


# ---------- senha ----------
def hash_senha(senha: str) -> str:
    return _ph.hash(senha)


def verificar_senha(senha: str, hash_: str) -> bool:
    try:
        return _ph.verify(hash_, senha)
    except (VerifyMismatchError, InvalidHashError):
        return False


def precisa_rehash(hash_: str) -> bool:
    return _ph.check_needs_rehash(hash_)


# ---------- JWT ----------
def _jwt(sub: int, typ: str, minutos: int, **extra) -> str:
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": str(sub),
        "typ": typ,  # "access" ou "2fa": um não serve no lugar do outro
        "iat": agora,
        "exp": agora + timedelta(minutes=minutos),
        "jti": uuid.uuid4().hex,
        **extra,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def criar_access_token(id_usuario: int, perfil: str) -> str:
    return _jwt(id_usuario, "access", ACCESS_MIN, perfil=perfil)


def criar_token_2fa(id_usuario: int) -> str:
    return _jwt(id_usuario, "2fa", PENDING_MIN)


def decodificar(token: str, typ: str) -> dict:
    erro = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Token inválido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        p = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALG],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError:
        raise erro
    if p["typ"] != typ:
        raise erro
    return p


# ---------- refresh token (opaco, só o hash vai pro banco) ----------
def hash_token(raw: str) -> str:
    # token tem 384 bits de entropia, então sha256 basta (argon2 aqui seria custo à toa)
    return hashlib.sha256(raw.encode()).hexdigest()


def novo_refresh() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


# ---------- código de 6 dígitos enviado por e-mail ----------
def gerar_codigo_email() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_codigo_email(id_usuario: int, codigo: str) -> str:
    # HMAC com chave do servidor: só 1 milhão de combinações, então SHA-256 puro seria quebrável offline
    return hmac.new(EMAIL_OTP_KEY.encode(), f"{id_usuario}:{codigo}".encode(), hashlib.sha256).hexdigest()