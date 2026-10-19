"""Preço médio, resultado realizado e proventos recebidos: as regras da carteira."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from src.storage.portfolio import PortfolioError, replay
from src.tools.analysis import _received
from src.tools.portfolio import _reached


def trade(side, quantity, price, day, ticker="PETR4.SA", created_at=None):
    return {
        "ticker": ticker,
        "side": side,
        "quantity": Decimal(str(quantity)),
        "unit_price": Decimal(str(price)),
        "price_currency": "BRL",
        "quote_currency": "BRL",
        "traded_on": date.fromisoformat(day),
        "created_at": created_at,
    }


def test_compra_recalcula_o_preco_medio_ponderado():
    position = replay([trade("compra", 100, 30, "2026-01-10"), trade("compra", 50, 36, "2026-02-10")])["PETR4.SA"]

    assert position.quantity == 150
    assert position.average_price == 32  # (100 × 30 + 50 × 36) / 150
    assert position.invested == 4800


def test_venda_reduz_a_quantidade_sem_mudar_o_preco_medio_e_realiza_o_resultado():
    position = replay([
        trade("compra", 100, 30, "2026-01-10"),
        trade("compra", 100, 40, "2026-02-10"),
        trade("venda", 50, 45, "2026-03-10"),
    ])["PETR4.SA"]

    assert position.quantity == 150
    assert position.average_price == 35
    assert position.realized == 500  # 50 × (45 − 35)


def test_venda_maior_que_a_posicao_na_data_e_recusada():
    # A compra posterior não salva a venda: a posição é a da data.
    trades = [
        trade("compra", 10, 30, "2026-01-10"),
        trade("venda", 20, 31, "2026-02-10"),
        trade("compra", 100, 32, "2026-03-10"),
    ]
    with pytest.raises(PortfolioError, match="10/02/2026"):
        replay(trades)


def test_operacoes_sao_aplicadas_pela_data_e_depois_pela_gravacao():
    # Fora de ordem na lista: a venda do mesmo dia gravada depois vem por último.
    early = datetime(2026, 1, 10, 10, tzinfo=timezone.utc)
    late = datetime(2026, 1, 10, 11, tzinfo=timezone.utc)
    positions = replay([
        trade("venda", 10, 31, "2026-01-10", created_at=late),
        trade("compra", 10, 30, "2026-01-10", created_at=early),
    ])

    assert positions["PETR4.SA"].quantity == 0
    assert positions["PETR4.SA"].realized == 10


def test_operacao_ainda_nao_gravada_vem_por_ultimo_no_dia():
    positions = replay([
        trade("venda", 10, 31, "2026-01-10"),
        trade("compra", 10, 30, "2026-01-10", created_at=datetime(2026, 1, 10, tzinfo=timezone.utc)),
    ])

    assert positions["PETR4.SA"].quantity == 0


def test_provento_conta_a_quantidade_do_fim_do_pregao_anterior_a_data_ex():
    trades = [trade("compra", 100, 30, "2026-01-10"), trade("compra", 50, 31, "2026-03-02")]
    payments = [
        {"ex_date": "2026-02-01", "amount": 0.5},
        # Comprou na própria data ex: as 50 novas não recebem.
        {"ex_date": "2026-03-02", "amount": 0.4},
        {"ex_date": "2026-04-01", "amount": 0.3},
    ]

    rows = _received("PETR4.SA", trades, payments)

    assert [(row["ex_date"], row["quantity"], row["received"]) for row in rows] == [
        ("2026-02-01", 100.0, 50.0),
        ("2026-03-02", 100.0, 40.0),
        ("2026-04-01", 150.0, 45.0),
    ]


def test_sem_posicao_na_data_ex_nao_ha_provento():
    rows = _received("PETR4.SA", [trade("compra", 100, 30, "2026-05-01")], [{"ex_date": "2026-04-01", "amount": 1.0}])

    assert rows == []


@pytest.mark.parametrize(
    ("operation", "price", "reached"),
    [("compra", 19.9, True), ("compra", 20.1, False), ("venda", 20.1, True), ("short", 19.9, False)],
)
def test_alvo_da_watchlist_depende_do_sentido_da_operacao(operation, price, reached):
    assert _reached(operation, price, 20.0) is reached
