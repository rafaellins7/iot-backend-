"""Log dos bloqueios dos controles de segurança (OTP e IDOR).

Toda mensagem leva o código de missão da equipe (MISSION_CODE no .env), como pede a atividade.
Vai para o console e para o arquivo SEGURANCA_LOG_FILE (padrão: seguranca.log), que serve de evidência.
"""
import logging
import os

MISSION_CODE = os.getenv("MISSION_CODE", "SEM-CODIGO")

log = logging.getLogger("seguranca")
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(), logging.FileHandler(os.getenv("SEGURANCA_LOG_FILE", "seguranca.log"), encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.propagate = False


def bloqueio(controle: str, motivo: str, id_usuario=None, **contexto) -> None:
    """Ex.: [K7Q2M9] BLOQUEIO OTP: codigo_reutilizado usuario=7"""
    extra = " ".join(f"{k}={v}" for k, v in contexto.items())
    log.warning("[%s] BLOQUEIO %s: %s usuario=%s %s", MISSION_CODE, controle, motivo, id_usuario, extra)
