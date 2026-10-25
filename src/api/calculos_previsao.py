import math

# ---------- Irrigação ----------
KC_MANGA = {"inducao_floral": 0.85, "maturacao": 0.91}
KC_UVA_MIN, KC_UVA_MAX = 0.50, 0.74
CHUVA_EFETIVA_FATOR = 0.80      # 80% da chuva registrada
PROB_CHUVA_MIN = 60             # % mínima para considerar chuva prevista
IRRIGACAO_MIN_MM = 1.0          # mm/dia
VPD_LIMIAR_KPA = 1.5

# ---------- Prejuízo ----------
FRACAO_BASE = {"baixo": 0.05, "medio": 0.15, "alto": 0.30}
TOLERANCIA_H = 2
ACRESCIMO_POR_HORA = 0.005      # 0,5 ponto percentual por hora excedente
FRACAO_MAXIMA = 1.0             # teto de segurança (o documento não define o limite)
STATUS_EXCLUIDOS = {"finalizado"}


def kc_cultura(cultura: str, fase: str | None = None, kc: float | None = None) -> float:
    c = cultura.strip().lower()
    if c == "manga":
        if kc is not None:
            return kc
        if fase not in KC_MANGA:
            raise ValueError("Para manga informe fase: 'inducao_floral' ou 'maturacao'.")
        return KC_MANGA[fase]
    if c == "uva":
        if kc is None:
            return round((KC_UVA_MIN + KC_UVA_MAX) / 2, 2)  # ponto médio da faixa 0,50–0,74
        if not KC_UVA_MIN <= kc <= KC_UVA_MAX:
            raise ValueError(f"Kc da uva deve ficar entre {KC_UVA_MIN} e {KC_UVA_MAX}.")
        return kc
    if kc is not None:
        return kc
    raise ValueError(f"Cultura '{cultura}' sem Kc cadastrado; informe kc manualmente.")


def vpd_kpa(temp_c: float, umidade_pct: float) -> float:
    es = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return round(es * (1 - umidade_pct / 100), 3)


def calcular_irrigacao(et0_mm, kc, chuva_registrada_mm=0.0,
                       chuva_prevista_mm=0.0, prob_chuva_pct=None, vpd=None) -> dict:
    chuva_prevista_usada = chuva_prevista_mm if (prob_chuva_pct is not None
                                                 and prob_chuva_pct >= PROB_CHUVA_MIN) else 0.0
    pe = CHUVA_EFETIVA_FATOR * (chuva_registrada_mm + chuva_prevista_usada)
    etc = et0_mm * kc
    n = max(0.0, etc - pe)
    return {
        "et0_mm": round(et0_mm, 2), "kc": kc, "etc_mm": round(etc, 2),
        "chuva_efetiva_mm": round(pe, 2), "necessidade_mm": round(n, 2),
        "precisa_irrigar": n >= IRRIGACAO_MIN_MM,
        "vpd_kpa": vpd,
        "alerta_vpd": vpd is not None and vpd >= VPD_LIMIAR_KPA,
    }


def converter_para_kg(quantidade: float, unidade: str, peso_caixa_kg: float | None = None) -> float:
    u = unidade.strip().lower()
    if u in ("kg", "quilograma", "quilogramas"):
        return quantidade
    if u in ("t", "tonelada", "toneladas"):
        return quantidade * 1000
    if u in ("caixa", "caixas"):
        if not peso_caixa_kg:
            raise ValueError("Unidade 'caixa' exige peso_caixa_kg (peso líquido de uma caixa).")
        return quantidade * peso_caixa_kg
    raise ValueError(f"Unidade '{unidade}' não suportada.")


def calcular_prejuizo(quantidade, unidade, preco_kg, nivel_risco, horas_fora_faixa,
                      peso_caixa_kg=None) -> dict:
    nivel = nivel_risco.strip().lower()
    if nivel not in FRACAO_BASE:
        raise ValueError("nivel_risco deve ser baixo, medio ou alto.")
    kg = converter_para_kg(quantidade, unidade, peso_caixa_kg)
    valor_carga = kg * preco_kg
    f_tempo = max(0.0, horas_fora_faixa - TOLERANCIA_H) * ACRESCIMO_POR_HORA
    fracao = min(FRACAO_BASE[nivel] + f_tempo, FRACAO_MAXIMA)
    return {
        "quantidade_kg": round(kg, 2), "valor_carga": round(valor_carga, 2),
        "fracao_risco": FRACAO_BASE[nivel], "fracao_tempo": round(f_tempo, 4),
        "fracao_perda": round(fracao, 4), "prejuizo_estimado": round(valor_carga * fracao, 2),
    }