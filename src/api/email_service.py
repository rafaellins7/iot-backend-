import logging
import os
import smtplib
from email.message import EmailMessage
 
log = logging.getLogger("email")
 
 
def _enviar(para: str, assunto: str, corpo: str) -> None:
    if os.getenv("EMAIL_MODO_DEV", "false").lower() == "true":
        print(f"\n[EMAIL_MODO_DEV] Para: {para}\nAssunto: {assunto}\n{corpo}\n")
        return
 
    msg = EmailMessage()
    msg["From"] = os.environ.get("EMAIL_FROM", os.environ["SMTP_USER"])
    msg["To"] = para
    msg["Subject"] = assunto
    msg.set_content(corpo)
 
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as s:
            s.starttls()
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    except Exception:
        # não logamos destinatário nem código; só o fato de ter falhado
        log.exception("Falha ao enviar e-mail de verificação")
 
 
def enviar_codigo_login(para: str, nome: str, codigo: str, validade_min: int) -> None:
    corpo = (
        f"Olá, {nome}.\n\n"
        f"Seu código de acesso ao Dashboard FVS é: {codigo}\n\n"
        f"Ele vale por {validade_min} minutos e só pode ser usado uma vez.\n\n"
        "Se não foi você quem tentou entrar, ignore este e-mail e troque a sua senha. "
        "Nunca compartilhe este código com ninguém.\n"
    )
    _enviar(para, f"{codigo} é o seu código de acesso", corpo)