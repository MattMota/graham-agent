"""Novas tentativas nas fontes externas, só para as falhas passageiras."""

import httpx
import pytest

from src.tools import market


class FakeGet:
    """Respostas em sequência no lugar do `httpx.get`; um item `Exception` é levantado."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.count = 0

    def __call__(self, url, **kwargs):
        self.count += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, request=httpx.Request("GET", url))


@pytest.fixture
def no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(market.time, "sleep", waits.append)
    return waits


def test_falha_passageira_tenta_de_novo_com_espera_exponencial(monkeypatch, no_sleep):
    fake = FakeGet(503, httpx.ConnectTimeout("lento"), 200)
    monkeypatch.setattr(market.httpx, "get", fake)

    response = market._get_with_retry("https://exemplo.com")

    assert response.status_code == 200 and fake.count == 3
    assert no_sleep == [0.5, 1.0]


def test_erro_de_requisicao_nao_se_repete(monkeypatch, no_sleep):
    fake = FakeGet(404)
    monkeypatch.setattr(market.httpx, "get", fake)

    assert market._get_with_retry("https://exemplo.com").status_code == 404
    assert fake.count == 1 and no_sleep == []


def test_esgotadas_as_tentativas_devolve_a_ultima_resposta(monkeypatch, no_sleep):
    fake = FakeGet(503, 503, 503)
    monkeypatch.setattr(market.httpx, "get", fake)

    assert market._get_with_retry("https://exemplo.com").status_code == 503
    assert fake.count == market.NETWORK_RETRIES + 1


def test_falha_de_conexao_persistente_sobe(monkeypatch, no_sleep):
    monkeypatch.setattr(market.httpx, "get", FakeGet(*[httpx.ConnectError("fora")] * 3))

    with pytest.raises(httpx.ConnectError):
        market._get_with_retry("https://exemplo.com")
