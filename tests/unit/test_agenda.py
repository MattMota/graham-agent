"""Agenda de eventos: datas da Yahoo, janelas e a origem de cada ativo."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.tools import analysis
from src.tools.context import ToolContext, ToolFailure

# A leitura da Yahoo sem o cache, guardada na coleta: o servidor dos testes de
# integração troca `analysis._events` pela sessão inteira.
read_events = analysis._events.__wrapped__


def utc_midnight(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def at(moment: str) -> int:
    return int(datetime.fromisoformat(moment).timestamp())


@pytest.fixture
def yahoo(monkeypatch):
    """Troca a Yahoo por um `info` escrito pelo teste, um por ticker."""
    infos: dict[str, dict] = {}
    monkeypatch.setattr(
        analysis.market, "_ticker", lambda ticker: SimpleNamespace(get_info=lambda: infos.get(ticker, {}))
    )
    return infos


def test_data_ex_e_lida_em_utc_e_nao_no_fuso_da_maquina(yahoo):
    # A Yahoo grava a data ex à meia-noite UTC; lida em UTC−3, viraria o dia anterior.
    yahoo["MSFT"] = {
        "quoteType": "EQUITY",
        "exchangeTimezoneName": "America/New_York",
        "exDividendDate": utc_midnight("2026-11-19"),
        "dividendDate": utc_midnight("2026-12-10"),
    }

    events = read_events("MSFT")

    assert events["ex_date"] == "2026-11-19"
    assert events["payment_date"] == "2026-12-10"


def test_resultado_e_lido_no_fuso_da_bolsa(yahoo):
    # 23h em São Paulo já é o dia seguinte em UTC.
    yahoo["VALE3.SA"] = {
        "quoteType": "EQUITY",
        "exchangeTimezoneName": "America/Sao_Paulo",
        "earningsTimestampStart": at("2026-10-29T23:00:00-03:00"),
        "earningsTimestampEnd": at("2026-10-29T23:00:00-03:00"),
        "isEarningsDateEstimate": False,
    }

    events = read_events("VALE3.SA")

    assert events["earnings_from"] == events["earnings_to"] == "2026-10-29"
    assert events["found"] is True


def test_ativo_que_a_yahoo_nao_conhece(yahoo):
    assert read_events("XXXX9.SA")["found"] is False


def data(**fields):
    return {
        "found": True, "ex_date": None, "payment_date": None,
        "earnings_from": None, "earnings_to": None, "earnings_estimated": False, **fields,
    }


def test_eventos_fora_da_janela_ficam_de_fora():
    found = analysis._dated(
        data(earnings_from="2026-09-01", earnings_to="2026-09-01", ex_date="2027-03-01", payment_date="2026-11-10"),
        "2026-10-19", "2027-01-17",
    )

    assert found == [{"date": "2026-11-10", "type": "pagamento"}]


def test_janela_de_resultado_nao_confirmado_que_comecou_antes_de_hoje():
    found = analysis._dated(
        data(earnings_from="2026-10-15", earnings_to="2026-10-25", earnings_estimated=True),
        "2026-10-19", "2027-01-17",
    )

    assert found == [{"date": "2026-10-15", "type": "resultado", "estimated": True, "until": "2026-10-25"}]


@pytest.fixture
def events(monkeypatch):
    """Os eventos de cada ticker, relativos a hoje, sem passar pela Yahoo."""
    today = date.today()
    soon = lambda days: (today + timedelta(days=days)).isoformat()  # noqa: E731
    table = {
        "VALE3.SA": data(earnings_from=soon(10), earnings_to=soon(10)),
        "MSFT": data(ex_date=soon(30), payment_date=soon(50)),
        "PETR4.SA": data(),
        "XXXX9.SA": {**data(), "found": False},
    }
    monkeypatch.setattr(analysis, "_events", lambda ticker: table[ticker])
    return table


async def test_agenda_de_ativos_pedidos_em_ordem_de_data(events):
    output = await analysis.agenda(ToolContext(), tickers=["MSFT", "VALE3.SA", "PETR4.SA", "XXXX9.SA"], days=90)

    assert [(event["ticker_name"], event["type"]) for event in output["events"]] == [
        ("VALE3.SA", "resultado"), ("MSFT", "data_ex"), ("MSFT", "pagamento"),
    ]
    assert output["without_events"] == ["PETR4.SA"]
    assert output["unavailable"] == ["XXXX9.SA"]
    # Sem usuário, não há origem nem quantidade.
    assert all("origin" not in event for event in output["events"])


async def test_janela_curta_corta_os_eventos_seguintes(events):
    output = await analysis.agenda(ToolContext(), tickers=["MSFT"], days=40)

    assert [event["type"] for event in output["events"]] == ["data_ex"]


async def test_ativos_pedidos_que_a_yahoo_nao_conhece_viram_erro(events):
    with pytest.raises(ToolFailure, match="XXXX9.SA"):
        await analysis.agenda(ToolContext(), tickers=["XXXX9.SA"])


async def test_sem_tickers_a_agenda_precisa_de_usuario(events):
    with pytest.raises(ToolFailure, match="usuário autenticado"):
        await analysis.agenda(ToolContext())
