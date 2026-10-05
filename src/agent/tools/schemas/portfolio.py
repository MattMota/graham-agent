"""Schemas de entrada das ferramentas de carteira e watchlist."""

from datetime import date
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.agent.tools.schemas import TickerSymbol

Quantity = Annotated[
    float,
    Field(
        title="Quantidade",
        description="Quantidade de unidades do ativo. Aceita frações, como em criptomoedas.",
        gt=0,
    ),
]

UnitPrice = Annotated[
    float,
    Field(
        title="Preço unitário",
        description="Preço por unidade praticado na operação, na moeda do preço.",
        gt=0,
    ),
]

TradeDate = Annotated[
    date,
    Field(
        title="Data da operação",
        description="Dia em que a operação foi feita, no formato AAAA-MM-DD. Não pode ser futura.",
    ),
]

WatchOperation = Annotated[
    Literal["compra", "venda", "short"],
    Field(
        title="Operação",
        description=(
            "O que o usuário pretende fazer ao atingir o preço alvo: 'compra', "
            "'venda' ou 'short' (venda a descoberto)."
        ),
        # Rótulos que a interface mostra no lugar dos valores.
        json_schema_extra={
            "x-labels": {"compra": "Compra", "venda": "Venda", "short": "Short (venda a descoberto)"}
        },
    ),
]

# Moedas aceitas como moeda do preço: todas têm câmbio na Yahoo Finance com o
# dólar e com o real, então o valor atual sempre pode ser convertido.
CURRENCIES = {
    "BRL": "Real brasileiro",
    "USD": "Dólar americano",
    "EUR": "Euro",
    "GBP": "Libra esterlina",
    "JPY": "Iene japonês",
    "CHF": "Franco suíço",
    "CAD": "Dólar canadense",
    "AUD": "Dólar australiano",
    "CNY": "Yuan chinês",
    "HKD": "Dólar de Hong Kong",
    "MXN": "Peso mexicano",
    "ARS": "Peso argentino",
    "CLP": "Peso chileno",
    "COP": "Peso colombiano",
}

CurrencyCode = Literal[
    "BRL", "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY", "HKD", "MXN", "ARS", "CLP", "COP"
]

CURRENCY_LABELS = {code: f"{code} · {name}" for code, name in CURRENCIES.items()}


def _upper_code(value: Optional[str]) -> Optional[str]:
    # Antes da validação: o modelo às vezes escreve 'brl'.
    return value.strip().upper() if isinstance(value, str) and value.strip() else None

TargetPrice = Annotated[
    float,
    Field(
        title="Preço alvo",
        description="Preço que dispara a operação, na moeda em que o ativo é cotado.",
        gt=0,
    ),
]


class _TickerArgs(BaseModel):
    ticker_name: TickerSymbol

    @field_validator("ticker_name")
    @classmethod
    def _clean(cls, value: str) -> str:
        return value.strip().upper()


class TradeInput(_TickerArgs):
    """Argumentos de uma compra ou venda registrada na carteira."""

    quantity: Quantity
    unit_price: UnitPrice
    traded_on: TradeDate
    currency: Optional[CurrencyCode] = Field(
        default=None,
        title="Moeda do preço",
        description=(
            "Moeda em que o usuário pagou e em que o preço unitário está, como 'BRL'. "
            "Sem ela, vale a moeda em que o ativo é cotado. Use quando ele pagou numa "
            "moeda diferente, como Bitcoin (BTC-USD) comprado em reais."
        ),
        json_schema_extra={"x-labels": CURRENCY_LABELS, "x-empty-label": "Moeda da cotação do ativo"},
    )

    @field_validator("currency", mode="before")
    @classmethod
    def _currency_code(cls, value: Optional[str]) -> Optional[str]:
        return _upper_code(value)

    @field_validator("traded_on")
    @classmethod
    def _not_in_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("A data da operação não pode ser futura.")
        return value


class PortfolioViewInput(BaseModel):
    """Filtros da consulta à carteira."""

    ticker_name: Optional[TickerSymbol] = Field(
        default=None, description="Mostra só este ativo. Sem ele, a carteira inteira."
    )
    currency: Optional[CurrencyCode] = Field(
        default=None,
        title="Moeda",
        description="Mostra só os ativos com preço nesta moeda, como 'BRL' ou 'USD'.",
    )
    include_trades: bool = Field(
        default=False,
        title="Incluir operações",
        description="Inclui a lista de compras e vendas, com datas e preços, além das posições.",
    )

    @field_validator("ticker_name", "currency", mode="before")
    @classmethod
    def _upper(cls, value: Optional[str]) -> Optional[str]:
        return _upper_code(value)


class WatchInput(_TickerArgs):
    """Argumentos de uma entrada nova na watchlist."""

    operation: WatchOperation
    target_price: TargetPrice
    quantity: Optional[Quantity] = Field(
        default=None,
        title="Quantidade",
        description="Opcional: quantas unidades operar quando o alvo for atingido.",
    )


class WatchRemoveInput(_TickerArgs):
    """Identifica a entrada da watchlist a remover."""

    operation: WatchOperation
    target_price: Optional[TargetPrice] = Field(
        default=None,
        title="Preço alvo",
        description=(
            "Preço alvo da entrada. Só é preciso quando há mais de uma entrada com "
            "o mesmo ativo e a mesma operação."
        ),
    )


class WatchViewInput(BaseModel):
    """Filtro da consulta à watchlist."""

    ticker_name: Optional[TickerSymbol] = Field(
        default=None, description="Mostra só este ativo. Sem ele, a watchlist inteira."
    )

    @field_validator("ticker_name")
    @classmethod
    def _upper(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else value
