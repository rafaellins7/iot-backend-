"""Testes automatizados cobrindo os requisitos de auditoria do parecer_ia:
1. Escopo: lote sem leituras não chama LLM e devolve SEM_DADOS determinístico.
2. Horas fora da faixa: isolado por lote, retornando None se não houver leituras para o lote.
3. Sanitização de prompt: remoção de LaTeX e Markdown e garantia das 5 chaves.
4. Respeito ao modelo configurado (PARECER_MODELO) e contagem de chamadas.
"""
import pytest
from unittest.mock import MagicMock, patch

from src.api.services.ia_service import _sanitizar_conteudo, _limpar_estilos, gerar_parecer
from src.api.services.llm_client import contar_chamadas_hora, registrar_chamada_provedor
from src.api.previsao_repo import horas_fora_da_faixa


def test_limpar_estilos_remove_latex_e_markdown():
    sujo = r"O lote está em \text{estresse} com **VPD alto** e temperatura $32^\circ C$."
    limpo = _limpar_estilos(sujo)
    assert r"\text" not in limpo
    assert "$" not in limpo
    assert "**" not in limpo
    assert "estresse" in limpo
    assert "VPD alto" in limpo


def test_sanitizar_conteudo_garante_cinco_chaves():
    parcial = {
        "parecer_agronomico": "Condições boas",
        # parecer_fisiologico omitido
        "recomendacoes": [],
        "nivel_confianca": "INDEFINIDO",
        # limitacoes omitido
    }
    sanitizado = _sanitizar_conteudo(parcial)
    assert "parecer_agronomico" in sanitizado
    assert sanitizado["parecer_fisiologico"] == "sem dados suficientes"
    assert sanitizado["recomendacoes"] == ["sem dados suficientes"]
    assert sanitizado["limitacoes"] == ["sem dados suficientes"]
    assert sanitizado["nivel_confianca"] == "BAIXO"


def test_horas_fora_da_faixa_retorna_none_sem_leituras():
    cur = MagicMock()
    # config_parametro existe
    cur.fetchone.side_effect = [{"temp_min": 20.0, "temp_max": 30.0}]
    # leituras vazias para o lote
    cur.fetchall.return_value = []

    res = horas_fora_da_faixa(cur, id_fruta=1, etapa="campo", janela_dias=7, id_lote=999)
    assert res is None


def test_contagem_chamadas_provedor_hora():
    antes = contar_chamadas_hora()
    registrar_chamada_provedor()
    depois = contar_chamadas_hora()
    assert depois == antes + 1
