import bcrypt


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_senha(senha: str, hash_salvo: str) -> bool:
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), hash_salvo.encode("utf-8"))
    except ValueError:
        return False