"""OTP (TOTP) ponta a ponta contra o PostgreSQL real do projeto. Pula se não houver banco.

Pré-requisito: banco com auth.sql + seguranca/sql/totp.sql e perfis cadastrados; variáveis DB_* no ambiente.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from src import database
from src.api import totp
from src.api.app import app
from src.api.security_auth import criar_access_token, hash_senha

SENHA = "Senha#Forte123"


def _conexao():
    try:
        return database.conectar()
    except Exception:
        return None


_c = _conexao()
pytestmark = pytest.mark.skipif(_c is None, reason="sem banco de dados configurado (DB_*)")
if _c:
    _c.close()

client = TestClient(app, client=("127.0.0.1", 50000))   # o log_acesso grava o IP como inet


@pytest.fixture
def usuario():
    conn = database.conectar()
    email = f"t{uuid.uuid4().hex[:8]}@teste.local"
    with conn.cursor() as cur:
        cur.execute("SELECT id_perfil FROM perfil WHERE nome = 'Produtor/Exportador'")
        perfil = cur.fetchone()[0]
        cur.execute("INSERT INTO usuario (nome, email, senha, status, data_cadastro, fk_perfil_id_perfil) "
                    "VALUES ('Teste', %s, %s, 'ativo', now(), %s) RETURNING id_usuario", (email, hash_senha(SENHA), perfil))
        uid = cur.fetchone()[0]
    conn.commit()
    yield {"id": uid, "email": email, "hdr": {"Authorization": f"Bearer {criar_access_token(uid, 'Produtor/Exportador')}"}}
    with conn.cursor() as cur:
        for t in ("totp_recuperacao", "totp_segredo", "refresh_token", "codigo_2fa_email"):
            cur.execute(f"DELETE FROM {t} WHERE fk_usuario_id_usuario = %s", (uid,))
        cur.execute("UPDATE usuario SET status = 'inativo' WHERE id_usuario = %s", (uid,))   # DELETE em usuario é bloqueado por trigger
    conn.commit()
    conn.close()


def _cadastrar(u):
    r = client.post("/auth/2fa/totp/iniciar", headers=u["hdr"])
    assert r.status_code == 200, r.text
    seg = r.json()["segredo_manual"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/") and r.json()["qr_code_png_base64"]
    r = client.post("/auth/2fa/totp/confirmar", headers=u["hdr"],
                    json={"codigo": totp.codigo_no_passo(seg, totp.passo_atual())})
    assert r.status_code == 200, r.text
    return seg, r.json()["codigos_recuperacao"]


def _senha_ok(u):
    r = client.post("/auth/login", json={"email": u["email"], "senha": SENHA})
    assert r.status_code == 200
    j = r.json()
    assert j["requer_2fa"] is True and j["metodo"] == "totp" and "access_token" not in j
    return j["token_temporario"]


def _verificar(tok, codigo):
    return client.post("/auth/2fa/verify", json={"token_temporario": tok, "codigo": codigo})


def test_senha_certa_sem_codigo_nao_da_acesso(usuario):
    _cadastrar(usuario)
    tok = _senha_ok(usuario)
    # o token temporário não serve como token de acesso
    assert client.get("/sensores", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_codigo_errado_recusado(usuario):
    seg, _ = _cadastrar(usuario)
    tok = _senha_ok(usuario)
    certo = totp.codigo_no_passo(seg, totp.passo_atual() + 1)
    errado = "000000" if certo != "000000" else "111111"
    assert _verificar(tok, errado).status_code == 401


def test_codigo_vencido_recusado(usuario):
    seg, _ = _cadastrar(usuario)
    tok = _senha_ok(usuario)
    assert _verificar(tok, totp.codigo_no_passo(seg, totp.passo_atual() - 5)).status_code == 401


def test_codigo_valido_aceito_e_nao_reutilizavel(usuario):
    seg, _ = _cadastrar(usuario)          # o cadastro já gastou o passo atual
    cod = totp.codigo_no_passo(seg, totp.passo_atual() + 1)
    r = _verificar(_senha_ok(usuario), cod)
    assert r.status_code == 200 and r.json()["access_token"]
    # mesmo código outra vez (novo login, mesma janela): recusado
    assert _verificar(_senha_ok(usuario), cod).status_code == 401


def test_codigo_do_cadastro_tambem_nao_reutiliza(usuario):
    seg, _ = _cadastrar(usuario)
    assert _verificar(_senha_ok(usuario), totp.codigo_no_passo(seg, totp.passo_atual())).status_code == 401


def test_recuperacao_vale_uma_vez(usuario):
    _, rec = _cadastrar(usuario)
    assert _verificar(_senha_ok(usuario), rec[0]).status_code == 200
    assert _verificar(_senha_ok(usuario), rec[0]).status_code == 401
    assert _verificar(_senha_ok(usuario), rec[1]).status_code == 200      # outro código continua valendo


def test_email_nao_substitui_totp(usuario):
    _cadastrar(usuario)
    tok = _senha_ok(usuario)
    assert client.post("/auth/2fa/reenviar", json={"token_temporario": tok}).status_code == 409


def test_regenerar_invalida_codigos_antigos(usuario):
    seg, rec = _cadastrar(usuario)
    r = client.post("/auth/2fa/totp/recuperacao/regenerar", headers=usuario["hdr"],
                    json={"codigo": totp.codigo_no_passo(seg, totp.passo_atual() + 1)})
    assert r.status_code == 200 and set(r.json()["codigos_recuperacao"]).isdisjoint(rec)
    assert _verificar(_senha_ok(usuario), rec[0]).status_code == 401


def test_confirmacao_com_codigo_errado_nao_ativa(usuario):
    client.post("/auth/2fa/totp/iniciar", headers=usuario["hdr"])
    assert client.post("/auth/2fa/totp/confirmar", headers=usuario["hdr"], json={"codigo": "000000"}).status_code == 400
    assert client.get("/auth/2fa/totp/status", headers=usuario["hdr"]).json()["ativo"] is False


def test_bloqueio_apos_5_falhas(usuario):
    seg, _ = _cadastrar(usuario)
    tok = _senha_ok(usuario)
    for _ in range(5):
        _verificar(tok, "000000")
    r = _verificar(tok, totp.codigo_no_passo(seg, totp.passo_atual() + 1))   # até o código certo é barrado
    assert r.status_code == 429


def test_desativar_exige_senha_e_codigo(usuario):
    seg, _ = _cadastrar(usuario)
    cod = totp.codigo_no_passo(seg, totp.passo_atual() + 1)
    assert client.post("/auth/2fa/totp/desativar", headers=usuario["hdr"], json={"senha": "errada", "codigo": cod}).status_code == 403
    assert client.post("/auth/2fa/totp/desativar", headers=usuario["hdr"], json={"senha": SENHA, "codigo": cod}).status_code == 204
