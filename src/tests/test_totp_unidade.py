"""TOTP sem banco: janela, reuso e códigos de recuperação."""
import pytest

from src.api import totp

SEG = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
T0 = 1_700_000_000.0


def _cod(passo):
    return totp.codigo_no_passo(SEG, passo)


def test_codigo_valido_aceito():
    p = totp.passo_atual(T0)
    assert totp.verificar(SEG, _cod(p), None, T0) == p


def test_codigo_errado_recusado():
    p = totp.passo_atual(T0)
    errado = "000000" if _cod(p) != "000000" else "111111"
    assert totp.verificar(SEG, errado, None, T0) is None


def test_codigo_vencido_recusado():
    p = totp.passo_atual(T0)
    assert totp.verificar(SEG, _cod(p - 2), None, T0) is None      # 60 s atrás: fora da janela
    assert totp.verificar(SEG, _cod(p + 2), None, T0) is None


def test_janela_tolera_um_passo():
    p = totp.passo_atual(T0)
    assert totp.verificar(SEG, _cod(p - 1), None, T0) == p - 1


def test_codigo_ja_usado_recusado():
    p = totp.passo_atual(T0)
    assert totp.verificar(SEG, _cod(p), p, T0) is None             # mesmo passo
    assert totp.verificar(SEG, _cod(p - 1), p, T0) is None         # passo anterior ao último aceito
    assert totp.verificar(SEG, _cod(p + 1), p, T0) == p + 1


@pytest.mark.parametrize("c", ["", "12345", "1234567", "abcdef", "12 456", "١٢٣٤٥٦"])
def test_formato_invalido(c):
    assert totp.verificar(SEG, c, None, T0) is None


def test_segredo_cifrado_ida_e_volta():
    c = totp.cifrar(SEG)
    assert SEG not in c and totp.decifrar(c) == SEG


def test_recuperacao_formato_e_hash():
    cods = totp.gerar_codigos_recuperacao()
    assert len(cods) == 10 and len(set(cods)) == 10
    assert totp.hash_recuperacao(1, cods[0]) == totp.hash_recuperacao(1, cods[0].lower().replace("-", " "))
    assert totp.hash_recuperacao(1, cods[0]) != totp.hash_recuperacao(2, cods[0])
