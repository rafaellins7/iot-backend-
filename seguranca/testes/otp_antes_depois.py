"""Teste do 2FA TOTP no login (senha certa SEM código não entra; errado/vencido/reusado não entra).

Uso (raiz do repo, com a API rodando; usuário de teste SEM TOTP cadastrado ainda):
  python seguranca/testes/otp_antes_depois.py --fase antes  --email t@x.com --senha 'Senha#123' --id-usuario 7
  python seguranca/testes/otp_antes_depois.py --fase depois --email t@x.com --senha 'Senha#123' --id-usuario 7
--fase antes: login só com a senha (sem TOTP cadastrado). Para o "antes" fiel, rode no commit anterior.
--fase depois: cadastra o TOTP (QR), e roda a bateria completa. Usa o relógio da máquina.
"""
import argparse

import pyotp
import requests

from _comum import BASE, Relatorio
from src.api import totp
from src.api.security_auth import criar_access_token

ap = argparse.ArgumentParser()
ap.add_argument("--fase", choices=["antes", "depois"], required=True)
ap.add_argument("--email", required=True)
ap.add_argument("--senha", required=True)
ap.add_argument("--id-usuario", type=int, required=True)
ap.add_argument("--perfil", default="Produtor/Exportador")
a = ap.parse_args()
r = Relatorio("otp")


def login():
    return requests.post(f"{BASE}/auth/login", json={"email": a.email, "senha": a.senha}).json()


def verificar(tok, cod):
    return requests.post(f"{BASE}/auth/2fa/verify", json={"token_temporario": tok, "codigo": cod})


if a.fase == "antes":
    j = login()
    r.linha(f"login só com a senha -> {sorted(j)}")
    r.linha("VULNERÁVEL: entrou só com a senha" if "access_token" in j else "pediu segundo fator (código por e-mail ou TOTP)")
    r.salvar("antes")
    raise SystemExit(0)

hdr = {"Authorization": f"Bearer {criar_access_token(a.id_usuario, a.perfil)}"}
r.linha("== Cadastro do segundo fator")
ini = requests.post(f"{BASE}/auth/2fa/totp/iniciar", headers=hdr)
r.checar("iniciar cadastro devolve QR Code (PNG) e URI otpauth", ini.status_code == 200 and ini.json().get("qr_code_png_base64") and ini.json()["otpauth_uri"].startswith("otpauth://"), f"-> {ini.status_code}")
seg = ini.json()["segredo_manual"]
app = pyotp.TOTP(seg)        # faz o papel do aplicativo autenticador
conf = requests.post(f"{BASE}/auth/2fa/totp/confirmar", headers=hdr, json={"codigo": app.now()})
r.checar("confirmar com o código do app ativa e entrega códigos de recuperação", conf.status_code == 200 and len(conf.json().get("codigos_recuperacao", [])) == 10, f"-> {conf.status_code}")
rec = conf.json()["codigos_recuperacao"]

r.linha("\n== Login")
j = login()
r.checar("senha certa SEM código: não recebe access_token", j.get("requer_2fa") and "access_token" not in j and j.get("metodo") == "totp")
tok = j["token_temporario"]
c = requests.get(f"{BASE}/sensores", headers={"Authorization": f"Bearer {tok}"}).status_code
r.checar("token temporário não abre rota protegida", c == 401, f"-> {c}")

proximo = totp.codigo_no_passo(seg, totp.passo_atual() + 1)      # ainda dentro da janela e diferente do usado no cadastro
errado = "000000" if proximo != "000000" else "111111"
c = verificar(tok, errado).status_code
r.checar("código ERRADO é recusado", c == 401, f"-> {c}")
c = verificar(tok, totp.codigo_no_passo(seg, totp.passo_atual() - 6)).status_code
r.checar("código VENCIDO (3 min atrás) é recusado", c == 401, f"-> {c}")
resp = verificar(tok, proximo)
r.checar("código VÁLIDO é aceito (access_token)", resp.status_code == 200 and "access_token" in resp.json(), f"-> {resp.status_code}")
tok2 = login()["token_temporario"]
c = verificar(tok2, proximo).status_code
r.checar("o MESMO código usado de novo é recusado (reuso)", c == 401, f"-> {c}")

r.linha("\n== Código de recuperação")
resp = verificar(login()["token_temporario"], rec[0])
r.checar("código de recuperação funciona na 1ª vez", resp.status_code == 200, f"-> {resp.status_code}")
c = verificar(login()["token_temporario"], rec[0]).status_code
r.checar("o mesmo código de recuperação NÃO funciona na 2ª vez", c == 401, f"-> {c}")

r.linha("\n== Tentativa de contorno")
c = requests.post(f"{BASE}/auth/2fa/reenviar", json={"token_temporario": login()["token_temporario"]}).status_code
r.checar("pedir código por e-mail no lugar do TOTP é negado (sem rebaixar o 2º fator)", c == 409, f"-> {c}")
r.salvar("depois")
raise SystemExit(1 if r.falhas else 0)
