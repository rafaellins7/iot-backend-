"""Teste de IDOR: o usuário A tenta ler, alterar e apagar o que é do usuário B trocando o ID.

Uso (raiz do repo, com a API rodando):
  python seguranca/testes/idor_antes_depois.py --fase depois \
      --usuario-a 7 --sensor-a 10 --usuario-b 8 --sensor-b 11 --lote-b 2
  --fase antes: rode no commit ANTERIOR ao escopo por dono (veja o README); aqui, 2xx = vulnerável.
Os tokens são emitidos com o JWT_SECRET do .env (testa a AUTORIZAÇÃO, não o login).
"""
import argparse

import requests

from _comum import BASE, Relatorio
from src.api.security_auth import criar_access_token

ap = argparse.ArgumentParser()
ap.add_argument("--fase", choices=["antes", "depois"], required=True)
ap.add_argument("--usuario-a", type=int, required=True)
ap.add_argument("--sensor-a", type=int, required=True)
ap.add_argument("--usuario-b", type=int, required=True)
ap.add_argument("--sensor-b", type=int, required=True)
ap.add_argument("--lote-b", type=int, required=True)
ap.add_argument("--perfil", default="Produtor/Exportador")
a = ap.parse_args()

hA = {"Authorization": f"Bearer {criar_access_token(a.usuario_a, a.perfil)}"}
hB = {"Authorization": f"Bearer {criar_access_token(a.usuario_b, a.perfil)}"}
r = Relatorio("idor")
sB, lB = a.sensor_b, a.lote_b

r.linha(f"\n== Dono continua usando o que é dele (A={a.usuario_a}, sensor {a.sensor_a}; B={a.usuario_b}, sensor {sB})")
for quem, h, s in (("A", hA, a.sensor_a), ("B", hB, sB)):
    c = requests.get(f"{BASE}/sensores/{s}", headers=h).status_code
    r.checar(f"{quem} lê o próprio sensor {s}", c == 200, f"-> {c}")

r.linha(f"\n== A tenta usar o sensor {sB} e o lote {lB} de B trocando o ID")
tentativas = [
    ("ler sensor",            "GET",    f"/sensores/{sB}", None),
    ("ler leituras agregadas", "GET",   f"/sensores/{sB}/leituras?periodo=24h", None),
    ("listar leituras",       "GET",    f"/leituras?id_sensor={sB}", None),
    ("última leitura",        "GET",    f"/leituras/ultima?id_sensor={sB}", None),
    ("estatísticas",          "GET",    f"/leituras/estatisticas?id_sensor={sB}", None),
    ("leituras rejeitadas",   "GET",    f"/leituras-rejeitadas?id_sensor={sB}", None),
    ("ler lote",              "GET",    f"/lotes/{lB}", None),
    ("alterar configuração",  "PUT",    f"/sensores/{sB}", {"nome": "alterado-por-A"}),
    ("alterar lote",          "PATCH",  f"/lotes/{lB}", {"destino": "alterado-por-A"}),
    ("desativar sensor",      "DELETE", f"/sensores/{sB}", None),
]
for nome, metodo, rota, corpo in tentativas:
    resp = requests.request(metodo, BASE + rota, headers=hA, json=corpo)
    bloqueado = resp.status_code in (403, 404)
    if a.fase == "antes":
        r.linha(f"[{'BLOQUEADO' if bloqueado else 'PASSOU (vulnerável)'}] {metodo} {rota} ({nome}) -> {resp.status_code}")
        r.falhas += 0 if not bloqueado else 0
    else:
        r.checar(f"{metodo} {rota} ({nome}) deve dar 403/404", bloqueado, f"-> {resp.status_code}")

r.linha("\n== Depois das tentativas, B ainda usa o sensor normalmente")
resp = requests.get(f"{BASE}/sensores/{sB}", headers=hB)
r.checar("B lê o sensor e o nome NÃO foi alterado", resp.status_code == 200 and resp.json().get("nome") != "alterado-por-A",
         f"-> {resp.status_code}")
r.salvar(a.fase)
raise SystemExit(0 if a.fase == "antes" else (1 if r.falhas else 0))
