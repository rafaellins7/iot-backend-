"""Fórmulas dos documentos IRRIGAÇÃO e PREJUÍZO ESTIMADO. Funções puras: os parâmetros
(fração, tolerância, Kc, limiares...) chegam de parametro_prejuizo / parametro_irrigacao."""
import math
import unicodedata

FRACAO_MAXIMA = 1.0  # teto de segurança: os documentos não definem o limite do efeito do tempo
STATUS_EXCLUIDOS = {"finalizado"}


def normalizar_nivel(nivel: str) -> str:
    """'Médio' -> 'medio' (risco_climatico e parametro_prejuizo podem divergir na acentuação)."""
    s = unicodedata.normalize("NFKD", nivel.strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def vpd_kpa(temp_c: float, umidade_pct: float) -> float:
    es = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return round(es * (1 - umidade_pct / 100), 3)


def calcular_irrigacao(et0_mm, kc, chuva_registrada_mm=0.0, chuva_prevista_mm=0.0,
                       prob_chuva_pct=None, vpd=None, *, chuva_efetiva_pct=80.0,
                       prob_chuva_min=60.0, irrigacao_min_mm=1.0, vpd_limite=1.5,
                       umidade_solo=None, umidade_solo_min=None) -> dict:
    prevista_usada = chuva_prevista_mm if (prob_chuva_pct is not None
                                           and prob_chuva_pct >= prob_chuva_min) else 0.0
    pe = (chuva_efetiva_pct / 100) * (chuva_registrada_mm + prevista_usada)
    etc = et0_mm * kc
    n = max(0.0, etc - pe)
    por_clima = n >= irrigacao_min_mm
    por_solo = (umidade_solo is not None and umidade_solo_min is not None
                and umidade_solo < umidade_solo_min)
    return {
        "et0_mm": round(et0_mm, 2), "kc": kc, "etc_mm": round(etc, 2),
        "chuva_efetiva_mm": round(pe, 2), "necessidade_mm": round(n, 2),
        "precisa_irrigar": por_clima or por_solo,
        "motivo": [m for m, ok in (("balanco_hidrico", por_clima), ("umidade_solo_baixa", por_solo)) if ok],
        "vpd_kpa": vpd, "alerta_vpd": vpd is not None and vpd >= vpd_limite,
    }


def converter_para_kg(quantidade: float, unidade: str, peso_caixa_kg: float | None = None) -> float:
    u = unidade.strip().lower()
    if u in ("kg", "quilograma", "quilogramas"):
        return quantidade
    if u in ("t", "tonelada", "toneladas"):
        return quantidade * 1000
    if u in ("caixa", "caixas"):
        if not peso_caixa_kg:
            raise ValueError("unidade 'caixa' exige peso_caixa_kg (peso líquido de uma caixa)")
        return quantidade * peso_caixa_kg
    raise ValueError(f"unidade '{unidade}' não suportada")


def calcular_prejuizo(quantidade, unidade, preco_kg, fracao_base, horas_fora_faixa,
                      tolerancia_h, acrescimo_hora, peso_caixa_kg=None) -> dict:
    kg = converter_para_kg(quantidade, unidade, peso_caixa_kg)
    valor_carga = kg * preco_kg
    f_tempo = max(0.0, horas_fora_faixa - tolerancia_h) * acrescimo_hora
    fracao = min(fracao_base + f_tempo, FRACAO_MAXIMA)
    return {"quantidade_kg": round(kg, 2), "valor_carga": round(valor_carga, 2),
            "fracao_risco": fracao_base, "fracao_tempo": round(f_tempo, 4),
            "fracao_perda": round(fracao, 4), "prejuizo_estimado": round(valor_carga * fracao, 2)}