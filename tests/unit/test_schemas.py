"""Os modelos de entrada: o que o modelo escreve e o que chega às ferramentas."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from src.tools.schemas.analysis import AgendaInput, IncomeInput, PerformanceInput
from src.tools.schemas.portfolio import TradeInput


def test_tickers_vao_para_maiusculas():
    assert IncomeInput.model_validate({"ticker_name": " petr4.sa "}).ticker_name == "PETR4.SA"
    assert AgendaInput.model_validate({"tickers": ["vale3.sa", "aapl"]}).tickers == ["VALE3.SA", "AAPL"]


def test_lista_vazia_de_tickers_vale_a_carteira():
    assert AgendaInput.model_validate({"tickers": []}).tickers is None


@pytest.mark.parametrize("days", [0, 366])
def test_janela_da_agenda_tem_limites(days):
    with pytest.raises(ValidationError):
        AgendaInput.model_validate({"days": days})


def test_agenda_aceita_no_maximo_20_ativos():
    with pytest.raises(ValidationError):
        AgendaInput.model_validate({"tickers": [f"T{i}" for i in range(21)]})


def test_desempenho_compara_no_maximo_quatro_ativos():
    with pytest.raises(ValidationError):
        PerformanceInput.model_validate({"tickers": ["A", "B", "C", "D", "E"]})


def test_desempenho_nao_comeca_hoje_nem_no_futuro():
    with pytest.raises(ValidationError, match="anterior a hoje"):
        PerformanceInput.model_validate({"tickers": ["PETR4.SA"], "start_date": date.today().isoformat()})


def trade(**fields):
    return {"ticker_name": "petr4.sa", "quantity": 10, "unit_price": 30.5, "traded_on": "2026-01-10", **fields}


def test_operacao_normaliza_ticker_e_moeda():
    args = TradeInput.model_validate(trade(currency="brl"))

    assert (args.ticker_name, args.currency) == ("PETR4.SA", "BRL")


@pytest.mark.parametrize(
    "fields",
    [
        {"quantity": 0},
        {"unit_price": -1},
        {"currency": "XYZ"},
        {"traded_on": (date.today() + timedelta(days=1)).isoformat()},
    ],
)
def test_operacao_recusa_valores_invalidos(fields):
    with pytest.raises(ValidationError):
        TradeInput.model_validate(trade(**fields))
