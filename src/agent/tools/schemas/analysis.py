"""Schemas de entrada das ferramentas de proventos e desempenho."""

from datetime import date
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.agent.tools.schemas import TickerSymbol


def _clean(value: Optional[str]) -> Optional[str]:
    return value.strip().upper() if isinstance(value, str) and value.strip() else None


class IncomeInput(BaseModel):
    """Argumentos da consulta de proventos."""

    ticker_name: Optional[TickerSymbol] = Field(
        default=None,
        description=(
            "Ativo a consultar. Sem ele, a consulta é sobre a carteira do usuário: quanto "
            "ele recebeu de proventos, pela quantidade que tinha em cada data ex."
        ),
    )
    months: Annotated[
        int,
        Field(
            title="Meses",
            description="Janela da consulta, em meses contados até hoje.",
            ge=1,
            le=120,
        ),
    ] = 12

    @field_validator("ticker_name", mode="before")
    @classmethod
    def _upper(cls, value: Optional[str]) -> Optional[str]:
        return _clean(value)


Period = Literal["1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y", "10y", "max"]


class PerformanceInput(BaseModel):
    """Argumentos da análise de desempenho."""

    tickers: Annotated[
        list[TickerSymbol],
        Field(
            title="Ativos",
            description="De 1 a 4 ativos para comparar, como ['PETR4.SA', 'VALE3.SA'].",
            min_length=1,
            max_length=4,
        ),
    ]
    period: Period = Field(
        default="1y",
        title="Período",
        description=(
            "Janela até hoje: '1mo', '3mo', '6mo', 'ytd' (desde o início do ano), '1y', "
            "'2y', '5y', '10y' ou 'max'. Ignorado quando há `start_date`."
        ),
    )
    start_date: Optional[date] = Field(
        default=None,
        title="Data de início",
        description=(
            "Começa a análise nesta data (AAAA-MM-DD) em vez do período, como a data em "
            "que o usuário comprou o ativo."
        ),
    )
    compare_index: bool = Field(
        default=True,
        title="Comparar com o índice",
        description="Inclui o Ibovespa (ativos da B3) ou o S&P 500 (os demais) na comparação.",
    )

    @field_validator("tickers", mode="before")
    @classmethod
    def _upper_all(cls, value: list[str]) -> list[str]:
        return [_clean(item) or item for item in value] if isinstance(value, list) else value

    @field_validator("start_date")
    @classmethod
    def _not_in_future(cls, value: Optional[date]) -> Optional[date]:
        if value and value >= date.today():
            raise ValueError("A data de início precisa ser anterior a hoje.")
        return value
