"""Parecer automático de IA (somente leitura para o usuário): prompt, texto de reserva e geração."""
import json
import logging

from pydantic import ValidationError

from src.api.schemas import ParecerEstruturadoSchema
from src.api.services.llm_client import LLMError, gerar_json

logger = logging.getLogger(__name__)

PROMPT_SISTEMA_PARECER = """
Você é um Engenheiro Agrônomo e Fisiologista Vegetal sênior especialista em agricultura de precisão.
Sua função é interpretar os dados numéricos fornecidos no JSON e redigir um parecer técnico, agronômico e fisiológico.

DIRETRIZES RÍGIDAS:
1. NÃO calcule ou altere nenhum número. Todos os valores numéricos já foram calculados pelo sistema.
2. Valores null significam "dado indisponível": não invente nem estime; cite a lacuna em "limitacoes".
3. Interprete os dados recebidos explicando os impactos fisiológicos na cultura.
4. Se a chave "contem_dados_simulados" for true, cite obrigatoriamente essa condição na lista de limitações.
5. Responda ESTRITAMENTE em formato JSON com as chaves: parecer_agronomico (texto), parecer_fisiologico (texto),
   recomendacoes (lista de textos), nivel_confianca ("ALTO", "MEDIO" ou "BAIXO") e limitacoes (lista de textos).
Responda SEMPRE com as duas chaves, parecer_agronomico e parecer_fisiologico. Se faltar dado, escreva 'Sem dados suficientes' em vez de omitir a chave.
"""


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
    try:
        bruto, modelo = gerar_json(
            PROMPT_SISTEMA_PARECER,
            f"Dados calculados do lote:\n{json.dumps(snapshot, ensure_ascii=False)}",
        )
        conteudo = ParecerEstruturadoSchema(**bruto).model_dump()
        return conteudo, modelo, False
    except (LLMError, ValidationError, TypeError) as err:
        logger.warning("Parecer de IA indisponível, usando texto de reserva: %s", str(err)[:200])
        return gerar_parecer_fallback(snapshot), "fallback-template", True
