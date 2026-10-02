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
    ),
]

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
    currency: Optional[str] = Field(
        default=None,
        title="Moeda do preço",
        description=(
            "Moeda em que o usuário pagou e em que o preço unitário está, como 'BRL'. "
            "Sem ela, vale a moeda em que o ativo é cotado. Use quando ele pagou numa "
            "moeda diferente, como Bitcoin (BTC-USD) comprado em reais."
        ),
        min_length=3,
        max_length=3,
    )

    @field_validator("currency")
    @classmethod
    def _currency_code(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else None

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
    currency: Optional[str] = Field(
        default=None,
        title="Moeda",
        description="Mostra só os ativos cotados nesta moeda, como 'BRL' ou 'USD'.",
        min_length=3,
        max_length=3,
    )
    include_trades: bool = Field(
        default=False,
        title="Incluir operações",
        description="Inclui a lista de compras e vendas, com datas e preços, além das posições.",
    )

    @field_validator("ticker_name", "currency")
    @classmethod
    def _upper(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else value


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
