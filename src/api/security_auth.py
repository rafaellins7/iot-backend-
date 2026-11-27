import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, status

JWT_SECRET = os.environ["JWT_SECRET"]
EMAIL_OTP_KEY = os.environ["EMAIL_OTP_KEY"]
JWT_ALG = "HS256"
ACCESS_MIN = int(os.getenv("ACCESS_MIN", "15"))  # JWT de acesso (configurável via env)
PENDING_MIN = 10     # token temporário do passo 1 (>= validade do código por e-mail)
REFRESH_DIAS = 7

_ph = PasswordHasher()  # argon2id com parâmetros padrão


# ---------- senhas ----------
# hash fixo usado quando o e-mail não existe (tempo de resposta igual; evita enumeração de usuários)
DUMMY_HASH = _ph.hash("dummy-password-for-timing-equalization")

_PREFIXOS_BCRYPT = ("$2a$", "$2b$", "$2y$")


def _eh_bcrypt(h: str) -> bool:
    return h.startswith(_PREFIXOS_BCRYPT)


def hash_senha(senha: str) -> str:
    """Única função que gera hash de senha no sistema. Sempre argon2id."""
    return _ph.hash(senha)


def verificar_senha(senha: str, h: str | None) -> bool:
    """Aceita argon2id (atual) e bcrypt (legado). Nunca lança exceção: hash inválido = False."""
    if not h:
        return False
    if _eh_bcrypt(h):
        try:
            return bcrypt.checkpw(senha.encode("utf-8")[:72], h.encode("utf-8"))
        except ValueError:
            return False
    try:
        return _ph.verify(h, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def precisa_rehash(h: str | None) -> bool:
    """True para bcrypt legado ou argon2 com parâmetros antigos. O login regrava com hash_senha."""
    if not h or _eh_bcrypt(h):
        return True
    try:
        return _ph.check_needs_rehash(h)
    except InvalidHashError:
        return True


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


# ---------- refresh token ----------
def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def novo_refresh() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


# ---------- código de 6 dígitos enviado por e-mail ----------
def gerar_codigo_email() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_codigo_email(id_usuario: int, codigo: str) -> str:
    return hmac.new(EMAIL_OTP_KEY.encode(), f"{id_usuario}:{codigo}".encode(), hashlib.sha256).hexdigest()

ALFABETO_ATIVACAO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def gerar_codigo_ativacao() -> str:
    c = "".join(secrets.choice(ALFABETO_ATIVACAO) for _ in range(10))
    return f"{c[:5]}-{c[5:]}"


def normalizar_codigo_ativacao(codigo: str) -> str:
    return codigo.replace("-", "").replace(" ", "").upper()


def validar_politica_senha(senha: str, email: str = "") -> list[str]:
    faltando = []
    if len(senha) < 8:
        faltando.append("minimo_8_caracteres")
    if not any(c.isupper() for c in senha):
        faltando.append("letra_maiuscula")
    if not any(c.islower() for c in senha):
        faltando.append("letra_minuscula")
    if not any(c.isdigit() for c in senha):
        faltando.append("numero")
    if not any(not c.isalnum() and not c.isspace() for c in senha):
        faltando.append("caractere_especial")
    local = email.split("@")[0].lower()
    if len(local) >= 3 and local in senha.lower():
        faltando.append("nao_conter_email")
    return faltando    