"""Utilidades dos testes de segurança. Rode os scripts a partir da RAIZ do repositório."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv

load_dotenv()
MISSAO = os.getenv("MISSION_CODE", "SEM-CODIGO")
BASE = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")


class Relatorio:
    def __init__(self, nome):
        self.nome, self.linhas, self.falhas = nome, [], 0
        self.linhas.append(f"# {nome}  |  missão {MISSAO}  |  {datetime.now():%Y-%m-%d %H:%M:%S}  |  API {BASE}")

    def linha(self, texto):
        print(texto)
        self.linhas.append(texto)

    def checar(self, descricao, ok, detalhe=""):
        self.falhas += 0 if ok else 1
        self.linha(f"[{'OK ' if ok else 'FALHA'}] {descricao} {detalhe}")

    def salvar(self, fase):
        pasta = os.path.join("seguranca", "evidencias")
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, f"{self.nome}_{fase}_{MISSAO}.txt")
        self.linha(f"\nResultado: {'TUDO CERTO' if self.falhas == 0 else str(self.falhas) + ' PONTO(S) FALHARAM'}")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write("\n".join(self.linhas) + "\n")
        print(f"evidência salva em {caminho}")
