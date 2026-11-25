"""Parecer automático de IA (somente leitura para o usuário): prompt, texto de reserva e geração."""
import json
import logging
import os
import re

from pydantic import ValidationError

from src.api.schemas import ParecerEstruturadoSchema
from src.api.services.llm_client import LLMError, gerar_json

logger = logging.getLogger(__name__)

PROMPT_SISTEMA_PARECER = """
Você é um Engenheiro Agrônomo e Fisiologista Vegetal sênior especialista em agricultura de precisão.
Sua função é interpretar os dados numéricos fornecidos no JSON e redigir um parecer técnico, agronômico e fisiológico.

DIRETRIZES RÍGIDAS DE FORMATAÇÃO E CONTEÚDO:
1. Responda exclusivamente em texto puro. NÃO utilize formatação LaTeX (como \\text, $, $$, barras invertidas). NÃO utilize formatação Markdown (como **, *, #, marcadores ou blocos de código).
2. É OBRIGATÓRIO responder em formato JSON contendo exatamente as 5 chaves a seguir, sem omitir nenhuma:
   - "parecer_agronomico" (string em texto corrido puro)
   - "parecer_fisiologico" (string em texto corrido puro)
   - "recomendacoes" (lista de strings em texto puro)
   - "nivel_confianca" (string: obrigatoriamente "ALTO", "MEDIO" ou "BAIXO")
   - "limitacoes" (lista de strings em texto puro)
3. Se faltar dado no snapshot para qualquer análise ou se um valor for null, NUNCA omita a chave; escreva "sem dados suficientes" em vez de omitir ou deixar em branco.
4. NÃO calcule ou altere nenhum número. Todos os valores numéricos já foram calculados pelo sistema.
5. Se "contem_dados_simulados" for true, cite obrigatoriamente essa condição na lista de limitações.
"""


def _limpar_estilos(texto: str) -> str:
    """Remove qualquer fragmento residual de LaTeX ou Markdown."""
    if not isinstance(texto, str):
        return texto
    t = re.sub(r'\\text\{([^}]*)\}', r'\1', texto)
    t = re.sub(r'\\[a-zA-Z]+', '', t)
    t = t.replace('$$', '').replace('$', '')
    t = re.sub(r'[*_#`]', '', t)
    return t.strip()


def _sanitizar_conteudo(d: dict) -> dict:
    if not isinstance(d, dict):
        return d
    limpo = {}
    for k, v in d.items():
        if isinstance(v, str):
            limpo[k] = _limpar_estilos(v)
        elif isinstance(v, list):
            limpo[k] = [_limpar_estilos(item) if isinstance(item, str) else item for item in v]
        else:
            limpo[k] = v

    for chave in ("parecer_agronomico", "parecer_fisiologico"):
        if not limpo.get(chave):
            limpo[chave] = "sem dados suficientes"
    for chave in ("recomendacoes", "limitacoes"):
        if not limpo.get(chave):
            limpo[chave] = ["sem dados suficientes"]
    if limpo.get("nivel_confianca") not in ("ALTO", "MEDIO", "BAIXO"):
        limpo["nivel_confianca"] = "BAIXO"
    return limpo


def gerar_parecer_fallback(dados: dict) -> dict:
    """Texto determinístico, usado quando a IA está indisponível. Aceita campos null."""
    vpd = dados.get("vpd_medio")
    prejuizo = dados.get("prejuizo_estimado_brl")
    horas = dados.get("horas_fora_da_faixa")
    simulado = dados.get("contem_dados_simulados", False)

    if vpd is None:
        fisiologico = "Sem leituras de ar recentes para calcular o VPD; não é possível avaliar o estresse hídrico/térmico."
        recomendacoes = ["Verificar se o sensor do lote está enviando leituras"]
    elif vpd > 2.0:
        fisiologico = f"VPD médio de {vpd:.2f} kPa indica estresse hídrico/térmico, induzindo ao fechamento estomático preventivo."
        recomendacoes = ["Aumentar a frequência dos ciclos de irrigação", "Monitorar estresse foliar no período da tarde"]
    else:
        fisiologico = f"VPD médio de {vpd:.2f} kPa adequado para a transpiração da cultura."
        recomendacoes = ["Manter o cronograma de irrigação planejado"]

    partes = []
    partes.append(f"O lote acumula {horas:g}h fora da faixa ideal." if horas is not None
                  else "Não há dados suficientes para calcular as horas fora da faixa ideal.")
    partes.append(f"Prejuízo estimado de R$ {prejuizo:.2f}." if prejuizo is not None
                  else "Ainda não há estimativa de prejuízo para este lote.")

    limitacoes = ["Análise gerada em modo de emergência (template determinístico), sem IA."]
    if simulado:
        limitacoes.append("Atenção: a análise utilizou dados simulados de sensores.")

    return {
        "parecer_agronomico": " ".join(partes),
        "parecer_fisiologico": fisiologico,
        "recomendacoes": recomendacoes,
        "nivel_confianca": "BAIXO" if vpd is None else "MEDIO",
        "limitacoes": limitacoes,
    }


def gerar_parecer(snapshot: dict) -> tuple[dict, str, bool]:
    """Devolve (conteudo, modelo, usou_fallback). Nunca levanta: se a IA falhar ou responder
    algo fora do formato, cai no texto determinístico."""
    modelo_unico = (os.getenv("PARECER_MODELO") or "").strip() or None
    try:
        bruto, modelo = gerar_json(
            PROMPT_SISTEMA_PARECER,
            f"Dados calculados do lote:\n{json.dumps(snapshot, ensure_ascii=False)}",
            modelo_override=modelo_unico,
        )
        bruto = _sanitizar_conteudo(bruto)
        conteudo = ParecerEstruturadoSchema(**bruto).model_dump()
        return conteudo, modelo, False
    except (LLMError, ValidationError, TypeError) as err:
        logger.warning("Parecer de IA indisponível, usando texto de reserva: %s", str(err)[:200])
        return gerar_parecer_fallback(snapshot), "fallback-template", True
