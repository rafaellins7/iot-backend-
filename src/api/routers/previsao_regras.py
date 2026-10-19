"""Todos os limiares abaixo são PROVISÓRIOS (o grupo define).
"""
from typing import List, Optional

# ----- janela de colheita -----
LIM_CHUVA_MM = 2.0          # acima disso o dia não é bom para colher
LIM_PROB_CHUVA_PCT = 50     # idem, para a probabilidade máxima de chuva do dia
FATOR_SEM_FAIXA = 0.8       # desconto na confiança quando não há faixa de campo cadastrada

# ----- risco climático: (limiar, pontos), do mais grave para o menos grave -----
TEMP_MAX = [(38.0, 2), (35.0, 1)]       # °C, máxima diária
CHUVA_DIA = [(20.0, 2), (10.0, 1)]      # mm/dia
VPD_DIURNO = [(3.0, 2), (2.0, 1)]       # kPa, média entre 09h e 16h
PONTOS_MAXIMOS = 6
HORAS_DIURNAS = range(9, 17)


def modelo_janela() -> str:
    return "regras-v1-janela-colheita"


def modelo_risco() -> str:
    return "regras-v1-risco-climatico"


def _pontos(valor: Optional[float], tabela) -> int:
    if valor is None:
        return 0
    for limiar, pts in tabela:
        if valor >= limiar:
            return pts
    return 0


def _media(valores) -> Optional[float]:
    v = [x for x in valores if x is not None]
    return round(sum(v) / len(v), 2) if v else None


# ---------------------------------------------------------------- janela
def avaliar_dia(dia: dict, faixa: Optional[dict]) -> dict:
    motivos = []
    chuva = dia.get("precipitation_sum")
    prob = dia.get("precipitation_probability_max")
    if chuva is None and prob is None:
        motivos.append("sem dados de chuva")
    if chuva is not None and chuva > LIM_CHUVA_MM:
        motivos.append(f"chuva prevista de {chuva:.1f} mm")
    if prob is not None and prob > LIM_PROB_CHUVA_PCT:
        motivos.append(f"probabilidade de chuva de {prob:.0f}%")
    if faixa:
        tmax, tmin = dia.get("temperature_2m_max"), dia.get("temperature_2m_min")
        if faixa.get("temp_max") is not None and tmax is not None and tmax > faixa["temp_max"]:
            motivos.append(f"máxima de {tmax:.1f} °C acima da faixa ({faixa['temp_max']:.1f} °C)")
        if faixa.get("temp_min") is not None and tmin is not None and tmin < faixa["temp_min"]:
            motivos.append(f"mínima de {tmin:.1f} °C abaixo da faixa ({faixa['temp_min']:.1f} °C)")
    return {
        "data": dia.get("time"),
        "adequado": not motivos,
        "motivos": motivos,
        "temp_min": dia.get("temperature_2m_min"),
        "temp_max": dia.get("temperature_2m_max"),
        "chuva_mm": chuva,
        "prob_chuva_pct": prob,
    }


def calcular_janela(dias: List[dict], faixa: Optional[dict]) -> dict:
    """Maior sequência de dias consecutivos adequados (empate: a mais cedo)."""
    avaliados = [avaliar_dia(d, faixa) for d in dias]

    melhor, atual = [], []
    for d in avaliados:
        if d["adequado"]:
            atual.append(d)
            if len(atual) > len(melhor):
                melhor = list(atual)
        else:
            atual = []

    if melhor:
        confs = [100 - d["prob_chuva_pct"] if d["prob_chuva_pct"] is not None else 50 for d in melhor]
        confianca = sum(confs) / len(confs)
        if not faixa:
            confianca *= FATOR_SEM_FAIXA
        inicio, fim = melhor[0]["data"], melhor[-1]["data"]
        n = len(melhor)
        resultado = f"Janela de {inicio} a {fim} ({n} dia{'s' if n > 1 else ''})"
        categoria = "baixo" if n >= 2 else "médio"
    else:
        inicio = fim = None
        n, confianca = 0, None
        resultado = f"Sem janela adequada nos próximos {len(avaliados)} dias"
        categoria = "alto"

    return {
        "inicio": inicio,
        "fim": fim,
        "n_dias": n,
        "probabilidade": round(confianca, 2) if confianca is not None else None,
        "categoria": categoria,   # risco de NÃO haver janela: 2+ dias = baixo, 1 = médio, 0 = alto
        "resultado": resultado,
        "faixa_campo": bool(faixa),
        "dias": avaliados,
    }


# ----------------------------------------------------------------- risco
def calcular_risco(dias: List[dict], horas: List[dict]) -> dict:
    datas = {d["time"] for d in dias}
    horas = [h for h in horas if (h.get("time") or "")[:10] in datas]
    diurnas = [h for h in horas if int(h["time"][11:13]) in HORAS_DIURNAS]

    tmax = max((d["temperature_2m_max"] for d in dias if d.get("temperature_2m_max") is not None), default=None)
    chuva = max((d["precipitation_sum"] for d in dias if d.get("precipitation_sum") is not None), default=None)
    vpd = _media(h.get("vapour_pressure_deficit") for h in diurnas)

    fatores, score = [], 0
    for rotulo, valor, tabela, fmt in [
        ("calor", tmax, TEMP_MAX, "máxima de {:.1f} °C"),
        ("chuva", chuva, CHUVA_DIA, "chuva de até {:.1f} mm em um dia"),
        ("vpd", vpd, VPD_DIURNO, "VPD diurno médio de {:.2f} kPa"),
    ]:
        pts = _pontos(valor, tabela)
        score += pts
        if pts:
            fatores.append({"fator": rotulo, "pontos": pts, "texto": fmt.format(valor)})

    nivel = "baixo" if score <= 1 else "médio" if score <= 3 else "alto"
    return {
        "nivel_risco": nivel,
        # Índice provisório (pontos / máximo), NÃO é probabilidade estatística.
        "probabilidade": round(100 * score / PONTOS_MAXIMOS, 2),
        "justificativa": "; ".join(f["texto"] for f in fatores) or "Sem fatores de risco relevantes no período",
        "temperatura": _media(h.get("temperature_2m") for h in horas),
        "umidade": _media(h.get("relative_humidity_2m") for h in horas),
        "periodo_inicio": min(datas) if datas else None,
        "periodo_fim": max(datas) if datas else None,
        "fatores": fatores,
    }