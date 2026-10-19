"""Classe de cada ativo, enquadramento e a conta do rebalanceamento."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.tools import allocation
from src.tools.context import ToolContext, ToolFailure
from src.tools.schemas.allocation import AllocationInput


@pytest.mark.parametrize(
    ("ticker", "quote_type", "name", "expected"),
    [
        ("PETR4.SA", "EQUITY", "Petróleo Brasileiro S.A. - Petrobras", "acoes_br"),
        ("TAEE11.SA", "EQUITY", "Transmissora Aliança de Energia Elétrica S.A.", "acoes_br"),
        ("MXRF11.SA", "EQUITY", "Maxi Renda Fundo De Investimento Imobiliaro - FII", "fundos"),
        ("KNRI11.SA", "EQUITY", "Kinea Renda Imobiliária Fundo de Investimento Imobiliário", "fundos"),
        ("RZAG11.SA", "EQUITY", "Riza Agro Fiagro", "fundos"),
        # Um FII com "índice" no nome, e um FI-Infra só com as siglas.
        ("KNIP11.SA", "EQUITY", "Kinea Indices Precos Fundo Investimento Imobiliario - FII", "fundos"),
        ("CPTI11.SA", "EQUITY", "Capitania Infra Fic Fi Infra Rf Cp", "fundos"),
        ("KDIF11.SA", "EQUITY", "Kinea Infra Fundo Investimento Cotas Fundos Investimento Direitos Creditorios Infraestrutura", "fundos"),
        ("HASH11.SA", "EQUITY", "HASHDEX NASDAQ CME CRYPTO INDEX FUNDO DE ÍNDICE - RESPONSABILIDADE LIMITADA", "etfs"),
        ("KLBN11.SA", "EQUITY", "Klabin S.A.", "acoes_br"),
        ("BOVA11.SA", "EQUITY", "ISHARES IBOVESPA CLASSE DE ÍNDICE - RESPONSABILIDADE LIMITADA", "etfs"),
        ("BOVV11.SA", "EQUITY", "It Now Ibovespa Fundo de Índice", "etfs"),
        ("AAPL34.SA", "EQUITY", "Apple Inc.", "exterior"),
        ("BIVB39.SA", "EQUITY", "Vanguard S&P 500 ETF", "exterior"),
        ("AAPL", "EQUITY", "Apple Inc.", "exterior"),
        ("SPY", "ETF", "SPDR S&P 500 ETF Trust", "etfs"),
        ("BTC-USD", "CRYPTOCURRENCY", "Bitcoin USD", "cripto"),
        ("^BVSP", "INDEX", "IBOVESPA", "outros"),
    ],
)
def test_classe_pelo_tipo_e_pelo_nome_da_yahoo(ticker, quote_type, name, expected):
    assert allocation.classify(ticker, quote_type, name) == expected


def test_alocacao_precisa_somar_100():
    with pytest.raises(ValidationError, match="somam 90%"):
        AllocationInput(acoes_br=50, fundos=20, etfs=20, exterior=0, cripto=0)
    assert AllocationInput(acoes_br=50, fundos=30, etfs=20, exterior=0, cripto=0).tolerance == 5


def asset(ticker, asset_class, quantity, price, currency="BRL", rate=1.0):
    return {
        "ticker_name": ticker, "asset_class": asset_class, "quantity": quantity,
        "price": price, "currency": currency, "rate": rate, "value": quantity * price * rate,
    }


def targets(**weights):
    row = {name: 0 for name in allocation.CLASSES}
    row.update(weights)
    return {**row, "tolerance": row.pop("tolerance", 5), "updated_at": datetime.now(timezone.utc)}


@pytest.fixture
def portfolio(monkeypatch):
    """A carteira, o alvo e a watchlist que o teste escrever, sem banco nem Yahoo."""
    state = {"assets": [], "missing": [], "targets": None, "watch": [], "classes": {}, "overrides": {}}

    async def holdings(context):
        return state["assets"], state["missing"]

    async def get_targets(pool, user_id):
        return state["targets"]

    async def list_watch(pool, user_id):
        return state["watch"]

    async def automatic_class(ticker):
        return state["classes"][ticker]

    async def list_overrides(pool, user_id):
        return state["overrides"]

    monkeypatch.setattr(allocation, "_holdings", holdings)
    monkeypatch.setattr(allocation.targets_store, "get_targets", get_targets)
    monkeypatch.setattr(allocation.store, "list_watch", list_watch)
    monkeypatch.setattr(allocation, "automatic_class", automatic_class)
    monkeypatch.setattr(allocation.targets_store, "list_overrides", list_overrides)
    return state


USER = ToolContext(pool=object(), user_id=uuid4())

# 60 mil em ações, 20 mil em fundos, 20 mil em ETFs.
HOLDINGS = [
    asset("PETR4.SA", "acoes_br", 2000, 30),
    asset("MXRF11.SA", "fundos", 2000, 10),
    asset("BOVA11.SA", "etfs", 200, 100),
]


async def test_enquadramento_mostra_desvio_e_status_pela_banda(portfolio):
    portfolio["assets"] = HOLDINGS
    portfolio["targets"] = targets(acoes_br=50, fundos=30, etfs=20)

    output = await allocation.view_allocation(USER)

    by_class = {item["asset_class"]: item for item in output["classes"]}
    assert output["total_value"] == 100_000
    assert (by_class["acoes_br"]["deviation_pp"], by_class["acoes_br"]["status"]) == (10, "acima")
    assert (by_class["fundos"]["deviation_pp"], by_class["fundos"]["status"]) == (-10, "abaixo")
    assert by_class["etfs"]["status"] == "dentro"
    assert output["in_range"] is False


async def test_enquadramento_sem_alvo_mostra_so_os_pesos(portfolio):
    portfolio["assets"] = HOLDINGS

    output = await allocation.view_allocation(USER)

    assert output["has_targets"] is False and output["in_range"] is None
    assert [item["weight_percent"] for item in output["classes"]] == [60, 20, 20, 0, 0]
    assert "definir_alocacao" in output["note"]


async def test_aporte_vai_as_classes_abaixo_do_alvo_sem_vender(portfolio):
    portfolio["assets"] = HOLDINGS
    portfolio["targets"] = targets(acoes_br=50, fundos=30, etfs=20)

    output = await allocation.suggest_rebalance(USER, contribution=10_000)

    # Total de 110 mil: faltam 13 mil em fundos e 2 mil em ETFs, e o aporte de
    # 10 mil se divide na mesma proporção (8.666,67 e 1.333,33).
    orders = {order["ticker_name"]: order for order in output["orders"]}
    assert set(orders) == {"MXRF11.SA", "BOVA11.SA"}
    assert (orders["MXRF11.SA"]["side"], orders["MXRF11.SA"]["quantity"]) == ("compra", 866)
    assert orders["BOVA11.SA"]["quantity"] == 13
    assert output["cash_left"] == 40  # 10.000 − 8.660 − 1.300


async def test_com_vendas_a_classe_acima_do_alvo_vende(portfolio):
    portfolio["assets"] = HOLDINGS
    portfolio["targets"] = targets(acoes_br=50, fundos=30, etfs=20)

    output = await allocation.suggest_rebalance(USER, allow_sales=True)

    orders = {order["ticker_name"]: order for order in output["orders"]}
    assert (orders["PETR4.SA"]["side"], orders["PETR4.SA"]["quantity"]) == ("venda", 333)  # 10 mil / 30
    assert (orders["MXRF11.SA"]["side"], orders["MXRF11.SA"]["quantity"]) == ("compra", 1000)
    assert "BOVA11.SA" not in orders
    after = {item["asset_class"]: item["weight_after"] for item in output["classes"]}
    assert after["acoes_br"] == pytest.approx(50, abs=0.1)


async def test_classe_sem_ativo_na_carteira_traz_candidatos_da_watchlist(portfolio):
    portfolio["assets"] = HOLDINGS
    portfolio["targets"] = targets(acoes_br=40, fundos=20, etfs=20, exterior=20)
    portfolio["watch"] = [{"ticker": "AAPL", "operation": "compra"}, {"ticker": "PETR4.SA", "operation": "venda"}]
    portfolio["classes"] = {"AAPL": "exterior", "PETR4.SA": "acoes_br"}

    output = await allocation.suggest_rebalance(USER, contribution=5_000)

    # Total de 105 mil: faltam 21 mil no exterior e mil em fundos e em ETFs; o
    # aporte se divide nessa proporção, e a parte do exterior espera um ativo.
    [pending] = output["unassigned"]
    assert pending["asset_class"] == "exterior" and pending["watchlist_candidates"] == ["AAPL"]
    assert pending["amount"] == pytest.approx(4565.22)
    assert {order["ticker_name"]: order["quantity"] for order in output["orders"]} == {"MXRF11.SA": 21, "BOVA11.SA": 2}
    assert output["cash_left"] == 4_590  # 5.000 − 210 − 200: inclui a parte sem ativo


async def test_cripto_compra_fracao_e_ativo_em_dolar_converte_pelo_cambio(portfolio):
    portfolio["assets"] = [asset("BTC-USD", "cripto", 0.1, 100_000, "USD", 5.0)]  # R$ 50 mil
    portfolio["targets"] = targets(cripto=100)

    output = await allocation.suggest_rebalance(USER, contribution=1_000)

    [order] = output["orders"]
    assert order["quantity"] == pytest.approx(0.002)  # 1.000 / (100.000 × 5)
    assert order["currency"] == "USD" and order["price"] == 100_000


async def test_sem_alvo_nao_ha_rebalanceamento(portfolio):
    portfolio["assets"] = HOLDINGS

    with pytest.raises(ToolFailure, match="definir_alocacao"):
        await allocation.suggest_rebalance(USER, contribution=1_000)


async def test_sem_cotacao_de_algum_ativo_a_conta_nao_fecha(portfolio):
    portfolio["assets"] = HOLDINGS
    portfolio["missing"] = ["XPTO3.SA"]
    portfolio["targets"] = targets(acoes_br=100)

    with pytest.raises(ToolFailure, match="XPTO3.SA"):
        await allocation.suggest_rebalance(USER)


async def test_classe_escolhida_pelo_usuario_vale_mais_que_a_automatica(portfolio):
    # O IVVB11 é um ETF pela regra; o usuário o conta como exterior. O MXRF11 ele tira da conta.
    portfolio["assets"] = [*HOLDINGS, asset("IVVB11.SA", "etfs", 50, 400)]
    portfolio["overrides"] = {"IVVB11.SA": "exterior", "MXRF11.SA": "fora"}
    portfolio["targets"] = targets(acoes_br=60, etfs=20, exterior=20)

    output = await allocation.view_allocation(USER)

    by_class = {item["asset_class"]: item for item in output["classes"]}
    assert output["total_value"] == 100_000  # 60 mil + 20 mil + 20 mil, sem os 20 mil do MXRF11
    assert by_class["exterior"]["value"] == 20_000 and by_class["exterior"]["status"] == "dentro"
    assert by_class["fundos"]["value"] == 0
    assert output["in_range"] is True
    sources = {item["ticker_name"]: item["class_source"] for item in output["assets"]}
    assert sources == {"PETR4.SA": "automatica", "BOVA11.SA": "automatica", "IVVB11.SA": "usuario"}
    assert output["outside_allocation"] == [{"ticker_name": "MXRF11.SA", "asset_class": "fora"}]


async def test_ativo_fora_da_alocacao_nao_recebe_nem_perde_no_rebalanceamento(portfolio):
    portfolio["assets"] = HOLDINGS
    portfolio["overrides"] = {"MXRF11.SA": "fora"}
    portfolio["targets"] = targets(acoes_br=50, etfs=50)

    output = await allocation.suggest_rebalance(USER, allow_sales=True)

    assert "MXRF11.SA" not in {order["ticker_name"] for order in output["orders"]}


async def test_candidato_da_watchlist_segue_a_classe_escolhida(portfolio):
    portfolio["assets"] = HOLDINGS
    portfolio["targets"] = targets(acoes_br=40, fundos=20, etfs=20, exterior=20)
    portfolio["watch"] = [{"ticker": "IVVB11.SA", "operation": "compra"}]
    portfolio["classes"] = {"IVVB11.SA": "etfs"}
    portfolio["overrides"] = {"IVVB11.SA": "exterior"}

    output = await allocation.suggest_rebalance(USER, contribution=5_000)

    [pending] = output["unassigned"]
    assert pending["asset_class"] == "exterior" and pending["watchlist_candidates"] == ["IVVB11.SA"]
