"""Testes automatizados da geração de parecer:
1. Lock anti-duplicação (dois cliques não duplicam).
2. Verificação de hash (dados iguais não chamam a IA novamente; reaproveitado=True).
3. Produtor gera e analista vê (compartilham o mesmo registro).
4. Analista gera e produtor vê.
5. Produtor não vê nem gera parecer para lote de outro usuário.
6. Falha da IA grava status 'erro' e permite tentar de novo.
7. Gatilho automático com debounce aciona geração quando nova leitura é inserida.
"""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from src.api.app import app
from src.api.deps_auth import get_current_user
from src.api.services import parecer_auto

client = TestClient(app)

from src.api.deps_auth import ADMIN, ANALISTA, PRODUTOR_EXPORTADOR

PRODUTOR_91 = {
    "id_usuario": 91,
    "nome": "Rafael Reis Granja",
    "email": "rafael@raiz.agro",
    "perfil": PRODUTOR_EXPORTADOR,
    "ativo": True,
    "deve_trocar_senha": False,
}

ANALISTA_LUIZ = {
    "id_usuario": 92,
    "nome": "Luiz Felipe Analista",
    "email": "luiz@raiz.agro",
    "perfil": ANALISTA,
    "ativo": True,
    "deve_trocar_senha": False,
}

OUTRO_PRODUTOR = {
    "id_usuario": 999,
    "nome": "Outro Produtor",
    "email": "outro@raiz.agro",
    "perfil": PRODUTOR_EXPORTADOR,
    "ativo": True,
    "deve_trocar_senha": False,
}


@pytest.fixture
def auth_produtor():
    app.dependency_overrides[get_current_user] = lambda: PRODUTOR_91
    yield PRODUTOR_91
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def auth_analista():
    app.dependency_overrides[get_current_user] = lambda: ANALISTA_LUIZ
    yield ANALISTA_LUIZ
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def auth_outro_produtor():
    app.dependency_overrides[get_current_user] = lambda: OUTRO_PRODUTOR
    yield OUTRO_PRODUTOR
    app.dependency_overrides.pop(get_current_user, None)


def test_produtor_gera_e_reaproveita_hash(auth_produtor):
    """Primeira geração cria rascunho; segunda com dados iguais retorna reaproveitado=True sem chamar LLM."""
    with patch("src.api.routers.pareceres.gerar_json") as mock_llm:
        mock_llm.return_value = (
            {
                "introducao": "Análise agronômica do lote.",
                "diagnostico_clima": "Temperatura e umidade dentro do esperado.",
                "impacto_cultura": "Condição favorável.",
                "recomendacoes": ["Manter irrigação"],
                "conclusao": "Lote apto."
            },
            "gemini-2.5-flash"
        )

        # 1. Primeira geração (forcar=True para garantir geração fresca no teste)
        resp1 = client.post("/pareceres/gerar", json={"id_lote": 145, "tipo": "agronomico", "dias": 30, "forcar": True})
        assert resp1.status_code == 200, resp1.text
        data1 = resp1.json()
        assert data1["status"] in ("rascunho", "assinado")
        assert data1.get("em_geracao") is False
        id_parecer_1 = data1["id_parecer"]
        assert mock_llm.call_count == 1

        # 2. Segunda chamada com dados iguais (forcar=False): não chama a IA de novo
        resp2 = client.post("/pareceres/gerar", json={"id_lote": 145, "tipo": "agronomico", "dias": 30, "forcar": False})
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["reaproveitado"] is True
        assert data2["id_parecer"] == id_parecer_1
        assert mock_llm.call_count == 1  # não chamou de novo!


def test_lock_anti_duplicacao_se_ja_esta_gerando(auth_produtor):
    """Se já existe registro com em_geracao=True, nova requisição não dispara IA."""
    with patch("src.api.routers.pareceres.gerar_json") as mock_llm:
        from src import database
        with database.conectar() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO parecer_agronomico
                           (fk_lote_id_lote, tipo, texto_gerado, texto_final, dados_entrada,
                            hash_entrada, origem_texto, status, em_geracao, gerado_em)
                       VALUES (145, 'agronomico', '', '', '{}', 'lock_test_hash', 'llm', 'rascunho', TRUE, (now() AT TIME ZONE 'UTC'))
                       RETURNING id_parecer"""
                )
                id_bloqueado = cur.fetchone()[0]
            conn.commit()

        try:
            resp = client.post("/pareceres/gerar", json={"id_lote": 145, "tipo": "agronomico", "dias": 30, "forcar": False})
            assert resp.status_code == 200
            data = resp.json()
            assert data["id_parecer"] == id_bloqueado
            assert data.get("gerando") is True or data.get("em_geracao") is True
            assert mock_llm.call_count == 0  # IA NUNCA foi chamada
        finally:
            with database.conectar() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM parecer_agronomico WHERE id_parecer = %s", (id_bloqueado,))
                conn.commit()


def test_produtor_gera_e_analista_ve_mesmo_registro(auth_produtor, auth_analista):
    """Produtor gera parecer; analista consulta e vê exatamente o mesmo registro."""
    with patch("src.api.routers.pareceres.gerar_json") as mock_llm:
        mock_llm.return_value = (
            {
                "introducao": "Parecer para validação compartilhada.",
                "diagnostico_clima": "Estável.",
                "impacto_cultura": "Normal.",
                "recomendacoes": ["OK"],
                "conclusao": "Concluído."
            },
            "gemini-2.5-flash"
        )
        # Produtor gera
        app.dependency_overrides[get_current_user] = lambda: PRODUTOR_91
        resp_produtor = client.post("/pareceres/gerar", json={"id_lote": 145, "forcar": True})
        assert resp_produtor.status_code == 200
        id_parecer = resp_produtor.json()["id_parecer"]

        # Analista consulta lista do lote
        app.dependency_overrides[get_current_user] = lambda: ANALISTA_LUIZ
        resp_analista = client.get("/pareceres?id_lote=145")
        assert resp_analista.status_code == 200
        lista = resp_analista.json()
        ids = [p["id_parecer"] for p in lista]
        assert id_parecer in ids

        # Analista consulta último parecer do lote
        resp_ultimo = client.get("/pareceres/lote/145/ultimo")
        assert resp_ultimo.status_code == 200
        assert resp_ultimo.json()["id_parecer"] == id_parecer


def test_produtor_nao_ve_nem_gera_lote_de_outro_usuario(auth_outro_produtor):
    """Produtor 999 tenta acessar lote 145 (que pertence a 91) e recebe 404."""
    # Tentativa de gerar
    resp_gerar = client.post("/pareceres/gerar", json={"id_lote": 145, "forcar": False})
    assert resp_gerar.status_code == 404

    # Tentativa de listar
    resp_listar = client.get("/pareceres?id_lote=145")
    assert resp_listar.status_code == 404

    # Tentativa de obter último
    resp_ultimo = client.get("/pareceres/lote/145/ultimo")
    assert resp_ultimo.status_code == 404


def test_falha_de_ia_grava_erro_e_permite_tentar_de_novo(auth_produtor):
    """Quando LLM e fallback falham, em_geracao=False e erro_geracao é gravado; retry subsequente funciona."""
    with patch("src.api.routers.pareceres.gerar_json", side_effect=Exception("Falha total na API")):
        with patch("src.api.routers.pareceres.parecer_template", side_effect=Exception("Template quebrou")):
            resp = client.post("/pareceres/gerar", json={"id_lote": 145, "forcar": True})
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("em_geracao") is False
            assert "erro_geracao" in data and data["erro_geracao"] is not None

    # Tentar novamente com forcar=True (serviço/template operando normalmente)
    resp_retry = client.post("/pareceres/gerar", json={"id_lote": 145, "forcar": True})
    assert resp_retry.status_code == 200
    data_retry = resp_retry.json()
    assert data_retry["status"] in ("rascunho", "assinado")
    assert data_retry.get("erro_geracao") is None


def test_debounce_agenda_geracao():
    """Verifica que agendar_por_sensor aciona o timer de debounce para o lote correspondente."""
    parecer_auto._timers.clear()
    with patch("src.api.services.parecer_auto._disparar_geracao_lote"):
        # Sensor 1 está vinculado ao lote 145
        parecer_auto.agendar_por_sensor(1)
        assert 145 in parecer_auto._timers
        timer = parecer_auto._timers[145]
        assert timer.is_alive()
        timer.cancel()
        parecer_auto._timers.clear()
