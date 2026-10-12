"""Tipos usados pelos esquemas de mais de um domínio."""

from typing import Annotated

from pydantic import Field

TickerSymbol = Annotated[
    str,
    Field(
        title="Ticker da ação",
        description=(
            "O código (ticker) da ação na Yahoo Finance. "
            "Ações brasileiras usam o sufixo '.SA'. "
            "Exemplos: 'AAPL' para Apple, 'BBAS3.SA' para Banco do Brasil."
        ),
        examples=["AAPL", "BBAS3.SA", "PETR4.SA"],
        min_length=1,
        max_length=20,
    ),
]
