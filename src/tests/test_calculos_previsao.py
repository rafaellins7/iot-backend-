import pytest
from src.api import calculos_previsao as c


def test_prejuizo_exemplo_do_documento():
    # 1000 kg x R$5 = R$5000; base 5% + (6h-2h) x 0,5% = 7% -> R$350
    r = c.calcular_prejuizo(1000, "kg", 5, 0.05, 6, 2, 0.005)
    assert r["valor_carga"] == 5000 and r["fracao_perda"] == 0.07 and r["prejuizo_estimado"] == 350


def test_prejuizo_dentro_da_tolerancia():
    assert c.calcular_prejuizo(100, "kg", 10, 0.15, 2, 2, 0.005)["fracao_perda"] == 0.15


def test_prejuizo_teto():
    assert c.calcular_prejuizo(100, "kg", 10, 0.30, 1000, 2, 0.005)["fracao_perda"] == 1.0


def test_conversao_unidades():
    assert c.converter_para_kg(2, "t") == 2000
    assert c.converter_para_kg(10, "caixa", 4.5) == 45
    with pytest.raises(ValueError):
        c.converter_para_kg(10, "caixa")


def test_normalizar_nivel():
    assert c.normalizar_nivel("Médio") == "medio" and c.normalizar_nivel(" ALTO ") == "alto"


def test_irrigacao_sem_chuva():
    r = c.calcular_irrigacao(5, 0.85)
    assert r["etc_mm"] == 4.25 and r["necessidade_mm"] == 4.25 and r["precisa_irrigar"]


def test_chuva_prevista_so_com_prob_minima():
    baixa = c.calcular_irrigacao(5, 0.85, 0, 10, 59)
    alta = c.calcular_irrigacao(5, 0.85, 0, 10, 60)
    assert baixa["chuva_efetiva_mm"] == 0 and alta["chuva_efetiva_mm"] == 8.0
    assert alta["necessidade_mm"] == 0 and not alta["precisa_irrigar"]


def test_limiar_parametrizado():
    assert not c.calcular_irrigacao(1.5, 0.6)["precisa_irrigar"]                       # ETc 0,9
    assert c.calcular_irrigacao(2, 0.6)["precisa_irrigar"]                              # ETc 1,2
    assert not c.calcular_irrigacao(2, 0.6, irrigacao_min_mm=2.0)["precisa_irrigar"]


def test_solo_seco_forca_irrigacao():
    r = c.calcular_irrigacao(1, 0.5, umidade_solo=20, umidade_solo_min=30)
    assert r["precisa_irrigar"] and r["motivo"] == ["umidade_solo_baixa"]


def test_vpd_alerta():
    vpd = c.vpd_kpa(35, 30)
    assert vpd >= 1.5 and c.calcular_irrigacao(5, 0.6, vpd=vpd)["alerta_vpd"]
    assert not c.calcular_irrigacao(5, 0.6, vpd=c.vpd_kpa(25, 80))["alerta_vpd"]