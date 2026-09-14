"""
Campos compartilhados entre os schemas de entrada e de saída das ferramentas.

Cada item aqui é um tipo anotado do Pydantic (`Annotated[tipo, Field(...)]`),
reutilizável tanto em modelos de `input.py` quanto de `output.py`.
"""

from typing import Annotated, Literal

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

CompanyName = Annotated[
    str,
    Field(
        title="Nome da empresa",
        description=(
            "O nome (completo ou parcial) da empresa. "
            "Exemplos: 'Banco do Brasil', 'Apple', 'Petrobras'."
        ),
        examples=["Banco do Brasil", "Apple", "Petrobras"],
        min_length=1,
    ),
]

IndustryLabel = Annotated[
    str,
    Field(
        title="Indústria",
        description=(
            "O nome da indústria (subsetor) conforme a classificação da Yahoo Finance. "
            "Exemplos: 'Banks - Regional', 'Software - Application', 'Oil & Gas E&P'."
        ),
        examples=["Banks - Regional", "Software - Application", "Oil & Gas E&P"],
        min_length=1,
    ),
]

# Regiões aceitas pelo endpoint de resumo de mercado da Yahoo (yfinance.MarketRegion).
MarketRegionCode = Annotated[
    Literal[
        "US",
        "GB",
        "ASIA",
        "EUROPE",
        "RATES",
        "COMMODITIES",
        "CURRENCIES",
        "CRYPTOCURRENCIES",
    ],
    Field(
        title="Região do mercado",
        description=(
            "A região/segmento de mercado a ser consultado. "
            "'US' e 'EUROPE' trazem os principais índices da região; "
            "'RATES', 'COMMODITIES', 'CURRENCIES' e 'CRYPTOCURRENCIES' trazem "
            "juros, commodities, câmbio e criptomoedas."
        ),
        examples=["US", "EUROPE", "CURRENCIES"],
    ),
]

CountryRegionCode = Annotated[
    str,
    Field(
        title="País de referência",
        description=(
            "Código ISO 3166-1 alpha-2 do país usado para filtrar as empresas listadas "
            "(ex.: 'US' para empresas americanas, 'BR' para empresas brasileiras)."
        ),
        examples=["US", "BR", "GB"],
        min_length=2,
        max_length=2,
        pattern=r"^[A-Za-z]{2}$",
    ),
]
