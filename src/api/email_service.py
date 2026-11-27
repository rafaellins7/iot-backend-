import logging
import os
import smtplib
from email.message import EmailMessage
 
log = logging.getLogger("email")
 
 
def _enviar(para: str, assunto: str, corpo: str, anexo=None, propagar_erro: bool = False) -> None:
    if os.getenv("EMAIL_MODO_DEV", "false").lower() == "true":
        extra = f"\n[anexo: {anexo[1]}]" if anexo else ""
        print(f"\n[EMAIL_MODO_DEV] Para: {para}\nAssunto: {assunto}\n{corpo}{extra}\n")
        return

    msg = EmailMessage()
    msg["From"] = os.environ.get("EMAIL_FROM", os.environ["SMTP_USER"])
    msg["To"] = para
    msg["Subject"] = assunto
    msg.set_content(corpo)
    if anexo:
        dados, nome_arquivo = anexo
        msg.add_attachment(dados, maintype="text", subtype="csv", filename=nome_arquivo)

    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as s:
            s.starttls()
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    except Exception:
        # não logamos destinatário nem código; só o fato de ter falhado
        log.exception("Falha ao enviar e-mail de verificação")
        if propagar_erro:
            raise
 
 
def enviar_codigo_login(para: str, nome: str, codigo: str, validade_min: int) -> None:
    corpo = (
        f"Olá, {nome}.\n\n"
        f"Seu código de acesso ao Dashboard FVS é: {codigo}\n\n"
        f"Ele vale por {validade_min} minutos e só pode ser usado uma vez.\n\n"
        "Se não foi você quem tentou entrar, ignore este e-mail e troque a sua senha. "
        "Nunca compartilhe este código com ninguém.\n"
    )
    _enviar(para, f"{codigo} é o seu código de acesso", corpo)

# primeiro acesso
def enviar_link_ativacao(para: str, nome: str, codigo: str, link: str, validade_h: int) -> None:
    corpo = (
        f"Olá, {nome}.\n\n"
        "Uma conta foi criada para você no Dashboard FVS.\n"
        f"Para ativá-la e criar a sua senha, use o código abaixo ou acesse o link (vale por {validade_h} horas e só pode ser usado uma vez):\n\n"
        f"Código de ativação: {codigo}\n"
        f"{link}\n\n"
        "No primeiro acesso você vai criar a sua própria senha e aceitar os Termos e Políticas de Segurança. "
        "Nunca compartilhe este código.\n\n"
        "Se você não esperava este convite, ignore este e-mail.\n"
    )
    _enviar(para, "Ative a sua conta", corpo)


def enviar_aviso_conta_ativada(para: str, nome: str) -> None:
    corpo = (
        f"Olá, {nome}.\n\n"
        "A sua conta no Dashboard FVS foi ativada e a senha foi criada.\n\n"
        "Se não foi você, avise o administrador do sistema imediatamente.\n"
    )
    _enviar(para, "Conta ativada", corpo)    

def enviar_link_reset_senha(para: str, nome: str, link: str, validade_min: int) -> None:
    corpo = (
        f"Olá, {nome}.\n\n"
        "Recebemos um pedido para redefinir a senha da sua conta no Dashboard FVS.\n"
        f"Para escolher uma nova senha, acesse (vale por {validade_min} minutos e só pode ser usado uma vez):\n\n"
        f"{link}\n\n"
        "Se não foi você, ignore este e-mail: sua senha continua a mesma.\n"
    )
    _enviar(para, "Redefinição de senha", corpo)


def enviar_aviso_senha_alterada(para: str, nome: str) -> None:
    corpo = (
        f"Olá, {nome}.\n\n"
        "A senha da sua conta no Dashboard FVS acabou de ser alterada.\n\n"
        "Se foi você, não precisa fazer nada. Se não reconhece essa alteração, "
        "use a opção \"Esqueci minha senha\" agora e avise o administrador do sistema.\n"
    )
    _enviar(para, "Sua senha foi alterada", corpo)


def enviar_relatorio(para: str, nome: str, titulo: str, csv_bytes: bytes, nome_arquivo: str) -> None:
    corpo = (
        f"Olá, {nome}.\n\n"
        f"Segue em anexo o relatório solicitado: {titulo}.\n\n"
        "Se você não pediu este relatório, avise o administrador do sistema.\n"
    )
    _enviar(para, f"Relatório: {titulo}", corpo, anexo=(csv_bytes, nome_arquivo), propagar_erro=True)