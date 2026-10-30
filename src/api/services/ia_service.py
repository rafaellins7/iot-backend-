import os
import json
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

PROMPT_SISTEMA_PARECER = """
Você é um Engenheiro Agrônomo e Fisiologista Vegetal sênior especialista em agricultura de precisão.
Sua função é interpretar os dados numéricos fornecidos no JSON e redigir um parecer técnico, agronômico e fisiológico.

DIRETRIZES RÍGIDAS:
1. NÃO calcule ou altere nenhum número. Todos os valores numéricos já foram calculados pelo sistema.
2. Interprete os dados recebidos explicando os impactos fisiológicos na cultura.
3. Se a chave "contem_dados_simulados" for true, cite obrigatoriamente essa condição na lista de limitações.
4. Responda ESTRITAMENTE em formato JSON.
"""

def gerar_parecer_fallback(dados: dict) -> dict:
    vpd = dados.get("vpd_medio", 0)
    prejuizo = dados.get("prejuizo_acumulado_brl", 0)
    horas = dados.get("horas_fora_da_faixa", 0)
    simulado = dados.get("contem_dados_simulados", False)

    if vpd > 2.0:
        fisiologico = f"VPD médio de {vpd:.2f} kPa indica estresse hídrico/térmico, induzindo ao fechamento estomático preventivo."
        recomendacoes = ["Aumentar a frequência dos ciclos de irrigação", "Monitorar estresse foliar no período da tarde"]
    else:
        fisiologico = f"VPD médio de {vpd:.2f} kPa adequado para a transpiração da cultura."
        recomendacoes = ["Manter o cronograma de irrigação planejado"]

    limitacoes = ["Análise gerada em modo de emergência (Template determinístico)."]
    if simulado:
        limitacoes.append("Atenção: A análise utilizou dados simulados de sensores.")

    return {
        "parecer_agronomico": f"O lote acumula {horas}h fora da faixa ideal, com prejuízo estimado de R$ {prejuizo:.2f}.",
        "parecer_fisiologico": fisiologico,
        "recomendacoes": recomendacoes,
        "nivel_confianca": "MEDIO",
        "limitacoes": limitacoes
    }

async def chamar_gemini_parecer(dados_entrada: dict) -> tuple[dict, str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY não configurada.")

    client = genai.Client(api_key=api_key)
    prompt_usuario = f"Dados calculados do lote:\n{json.dumps(dados_entrada, ensure_ascii=False)}"

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt_usuario,
        config=types.GenerateContentConfig(
            system_instruction=PROMPT_SISTEMA_PARECER,
            response_mime_type="application/json",
            temperature=0.2
        ),
    )

    return json.loads(response.text), "gemini-2.5-flash"