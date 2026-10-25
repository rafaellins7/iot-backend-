from typing import Optional


def nome_fruta(cur, id_fruta):
    cur.execute("SELECT nome FROM fruta WHERE id_fruta = %s", (id_fruta,))
    r = cur.fetchone()
    return r["nome"] if r else None


def lotes_para_prejuizo(cur, id_lote: Optional[int]):
    sql = """SELECT l.id_lote, l.quantidade, l.unidade, l.fk_fruta_id_fruta AS id_fruta,
                    fn_etapa_lote(l.status) AS etapa
             FROM lote l WHERE lower(l.status::text) <> 'finalizado'"""
    args = ()
    if id_lote is not None:
        sql += " AND l.id_lote = %s"
        args = (id_lote,)
    cur.execute(sql + " ORDER BY l.id_lote", args)
    return cur.fetchall()


def nivel_risco_atual(cur, id_lote):
    cur.execute("""SELECT nivel_risco FROM risco_climatico
                   WHERE fk_lote_id_lote = %s ORDER BY data_previsao DESC LIMIT 1""", (id_lote,))
    r = cur.fetchone()
    return r["nivel_risco"] if r else None


def parametro_prejuizo(cur, nivel_norm: str, so_aprovados: bool):
    variantes = [nivel_norm] + (["médio"] if nivel_norm == "medio" else [])
    cur.execute(f"""SELECT fracao_perda, tolerancia_horas, acrescimo_hora, periodo_analise_dias,
                           validade_preco_dias, aprovado
                    FROM parametro_prejuizo WHERE nivel_risco = ANY(%s)
                    {'AND aprovado' if so_aprovados else ''}""", (variantes,))
    return cur.fetchone()


def parametro_irrigacao(cur, id_fruta, so_aprovados: bool):
    cur.execute(f"""SELECT kc, fase_cultura, chuva_efetiva_percentual, probabilidade_chuva_minima,
                           irrigacao_minima_mm, vpd_limite_kpa, umidade_solo_minima, aprovado
                    FROM parametro_irrigacao WHERE fk_fruta_id_fruta = %s
                    {'AND aprovado' if so_aprovados else ''}""", (id_fruta,))
    return cur.fetchone()


def preco_kg_atual(cur, id_fruta, validade_dias):
    cur.execute("""SELECT preco_kg FROM dado_mercado                          -- ASSUMIDO
                   WHERE fk_fruta_id_fruta = %s AND data_hora >= now() - make_interval(days => %s)
                   ORDER BY data_hora DESC LIMIT 1""", (id_fruta, int(validade_dias)))
    r = cur.fetchone()
    return float(r["preco_kg"]) if r else None


def horas_fora_da_faixa(cur, id_fruta, etapa, janela_dias):
    """Horas da sequência ininterrupta de leituras fora da faixa (config_parametro), até a mais recente."""
    cur.execute("""SELECT temp_min, temp_max FROM config_parametro
                   WHERE fk_fruta_id_fruta = %s AND etapa = %s LIMIT 1""", (id_fruta, etapa))
    faixa = cur.fetchone()
    if not faixa:
        return None
    cur.execute("""SELECT l.temperatura, l.data_hora FROM leitura_climatica l   -- colunas: ASSUMIDO
                   JOIN sensor s ON s.id_sensor = l.fk_sensor_id_sensor
                   WHERE s.ambiente <> 'solo'
                     AND l.data_hora >= (SELECT max(data_hora) FROM leitura_climatica)
                                        - make_interval(days => %s)
                   ORDER BY l.data_hora DESC""", (int(janela_dias),))
    leituras = cur.fetchall()
    if not leituras:
        return None
    fim = inicio = leituras[0]["data_hora"]
    for r in leituras:
        if faixa["temp_min"] <= r["temperatura"] <= faixa["temp_max"]:
            break
        inicio = r["data_hora"]
    return round((fim - inicio).total_seconds() / 3600, 2)


def ultima_leitura(cur, solo: bool):
    cur.execute(f"""SELECT l.temperatura, l.umidade, l.data_hora, s.origem
                    FROM leitura_climatica l JOIN sensor s ON s.id_sensor = l.fk_sensor_id_sensor
                    WHERE s.ambiente {'=' if solo else '<>'} 'solo'
                    ORDER BY l.data_hora DESC LIMIT 1""")   
    return cur.fetchone()