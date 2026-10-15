import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_conn  

router = APIRouter(prefix="/viagens", tags=["viagens"])

SQL_VIAGENS = """
SELECT v.id_viagem, v.status AS status_viagem,
       v.saida,
       COALESCE(v.chegada_prevista,
                v.saida + r.duracao_min * interval '1 minute') AS chegada_prevista,
       l.id_lote, l.quantidade, l.unidade, l.destino AS destino_lote,
       p.nome AS porto_nome, p.uf AS porto_uf,
       p.latitude AS porto_lat, p.longitude AS porto_lng,
       r.origem_nome, r.distancia_km, r.tracado,
       pp.prejuizo_estimado AS risco_valor,
       rc.nivel_risco, rc.probabilidade AS risco_probabilidade
FROM viagem v
JOIN lote  l ON l.id_lote  = v.fk_lote_id_lote
JOIN porto p ON p.id_porto = v.fk_porto_id_porto
LEFT JOIN LATERAL (
    SELECT * FROM rota
    WHERE fk_porto_id_porto = v.fk_porto_id_porto
    ORDER BY atualizado_em DESC NULLS LAST
    LIMIT 1
) r ON TRUE
LEFT JOIN LATERAL (
    SELECT prejuizo_estimado FROM previsao_prejuizo
    WHERE fk_lote_id_lote = l.id_lote
    ORDER BY data_previsao DESC LIMIT 1
) pp ON TRUE
LEFT JOIN LATERAL (
    SELECT nivel_risco, probabilidade FROM risco_climatico
    WHERE fk_lote_id_lote = l.id_lote
    ORDER BY data_previsao DESC LIMIT 1
) rc ON TRUE
"""


def _haversine_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _normalizar_tracado(t):
    """Aceita GeoJSON LineString, lista [[a, b], ...] ou [{lat, lng}, ...].
    Retorna lista de (lat, lng)."""
    if not t:
        return []
    if isinstance(t, dict):
        t = t.get("coordinates") or t.get("pontos") or []
    pts = []
    for p in t:
        if isinstance(p, dict):
            a = p.get("lat", p.get("latitude"))
            b = p.get("lng", p.get("lon", p.get("longitude")))
        else:
            a, b = p[0], p[1]
        a, b = float(a), float(b)
        # no Brasil |lat| < |lng|; garante a ordem (lat, lng) mesmo se vier como GeoJSON
        pts.append((a, b) if abs(a) <= abs(b) else (b, a))
    return pts


def _posicao(pts, fracao):
    """Ponto na polilinha correspondente à fração (0 a 1) do percurso."""
    if len(pts) < 2:
        return None
    seg = [_haversine_km(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    alvo, acum = sum(seg) * fracao, 0.0
    for i, d in enumerate(seg):
        if acum + d >= alvo or i == len(seg) - 1:
            f = 0 if d == 0 else min((alvo - acum) / d, 1)
            return (
                pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f,
                pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f,
            )
        acum += d


def _num(v):
    return float(v) if v is not None else None


def _montar(row: dict) -> dict:
    agora = datetime.now()  # colunas são timestamp sem fuso
    saida, eta = row["saida"], row["chegada_prevista"]
    total = (eta - saida).total_seconds()

    if row["status_viagem"] == "concluida":
        fracao = 1.0
    elif row["status_viagem"] in ("programada", "cancelada") or agora <= saida:
        fracao = 0.0
    elif total <= 0:
        fracao = 1.0
    else:
        fracao = min((agora - saida).total_seconds() / total, 1.0)

    pos = _posicao(_normalizar_tracado(row["tracado"]), fracao)
    restante_h = max((eta - agora).total_seconds() / 3600, 0)

    return {
        "id_viagem": row["id_viagem"],
        "status": row["status_viagem"],
        "lote": {
            "id_lote": row["id_lote"],
            "quantidade": row["quantidade"],
            "unidade": row["unidade"],
            "destino": row["destino_lote"],
        },
        "origem": row["origem_nome"],
        "destino": {
            "nome": row["porto_nome"],
            "uf": row["porto_uf"],
            "lat": _num(row["porto_lat"]),
            "lng": _num(row["porto_lng"]),
        },
        "saida": saida,
        "eta": eta,
        "progresso_pct": round(fracao * 100, 1),
        "tempo_restante_h": round(restante_h, 1),
        "atrasada": fracao < 1 and agora > eta,
        "posicao_estimada": (
            {"lat": round(pos[0], 5), "lng": round(pos[1], 5), "estimada": True}
            if pos else None
        ),
        "risco": {
            "valor": _num(row["risco_valor"]),
            "nivel": row["nivel_risco"],
            "probabilidade": _num(row["risco_probabilidade"]),
        },
    }


@router.get("")
def listar_viagens(status: str | None = None, conn=Depends(get_conn)):
    sql = SQL_VIAGENS + (" WHERE v.status = %s" if status else "") + " ORDER BY v.saida DESC"
    with conn.cursor() as cur:
        cur.execute(sql, (status,) if status else None)
        cols = [c[0] for c in cur.description]
        return [_montar(dict(zip(cols, r))) for r in cur.fetchall()]


@router.get("/{id_viagem}")
def obter_viagem(id_viagem: int, conn=Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(SQL_VIAGENS + " WHERE v.id_viagem = %s", (id_viagem,))
        r = cur.fetchone()
        if not r:
            raise HTTPException(404, "Viagem não encontrada")
        cols = [c[0] for c in cur.description]
        return _montar(dict(zip(cols, r)))