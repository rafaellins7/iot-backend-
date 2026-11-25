from datetime import datetime, timedelta, timezone

from src.api.routers import dashboard_stream as ds


class _Cur:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.row, self.fechada = row, False

    def cursor(self):
        return _Cur(self.row)

    def close(self):
        self.fechada = True


def _agora():
    return datetime.now(timezone.utc)


def test_buscar_ultima_leitura_usa_a_conexao_do_projeto_e_fecha(monkeypatch):
    # antes: `with get_conn() as conn` quebrava (get_conn é um gerador) e o stream sempre simulava
    dh = _agora()
    conn = _Conn((27.4, 61.2, dh, "Sensor 1"))
    monkeypatch.setattr(ds.database, "conectar", lambda: conn)
    assert ds.buscar_ultima_leitura() == {
        "temperatura": 27.4, "umidade": 61.2, "data_hora": dh, "sensor": "Sensor 1"}
    assert conn.fechada


def test_sem_leitura_no_banco_devolve_none(monkeypatch):
    monkeypatch.setattr(ds.database, "conectar", lambda: _Conn(None))
    assert ds.buscar_ultima_leitura() is None


def test_payload_real_quando_a_leitura_e_recente(monkeypatch):
    dh = _agora() - timedelta(minutes=2)
    monkeypatch.setattr(ds, "buscar_ultima_leitura", lambda: {
        "temperatura": 27.4, "umidade": 61.2, "data_hora": dh, "sensor": "Sensor 1"})
    p = ds.montar_payload()
    assert p["origem"] == "real" and p["temperatura"] == 27.4 and p["sensor"] == "Sensor 1"


def test_payload_real_offline_quando_a_leitura_esta_velha(monkeypatch):
    dh = _agora() - timedelta(minutes=30)
    monkeypatch.setattr(ds, "buscar_ultima_leitura", lambda: {
        "temperatura": 27.4, "umidade": 61.2, "data_hora": dh, "sensor": "Sensor 1"})
    p = ds.montar_payload()
    assert p["origem"] == "real" and p["status"] == "offline" and p["timestamp"] == dh.isoformat()


def test_banco_fora_do_ar_nao_derruba_o_stream(monkeypatch):
    def quebra():
        raise RuntimeError("banco indisponível")
    monkeypatch.setattr(ds, "buscar_ultima_leitura", quebra)
    p = ds.montar_payload()
    assert p["status"] == "sem_dados"


# ---------------------------------------------------------------- ticket do stream
def test_ticket_e_de_uso_unico():
    t = ds.emitir_ticket(7)
    assert ds.consumir_ticket(t) is True
    assert ds.consumir_ticket(t) is False      # já usado


def test_ticket_desconhecido_ou_vencido_e_recusado(monkeypatch):
    assert ds.consumir_ticket("ticket-que-nunca-existiu-123456") is False
    t = ds.emitir_ticket(7)
    ds._tickets[t] = (ds.time.monotonic() - 1, 7)   # força vencimento
    assert ds.consumir_ticket(t) is False
