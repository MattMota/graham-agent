"""Schemas de entrada (argumentos) das ferramentas do agente."""

import difflib
import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator
from yfinance.const import SECTOR_INDUSTY_MAPPING

from src.agent.tools.schemas import (
    CompanyName,
    CountryRegionCode,
    IndustryLabel,
    MarketRegionCode,
    TickerSymbol,
)

ResultLimit = Annotated[
    int,
    Field(
        title="Quantidade de resultados",
        description="Número máximo de resultados a retornar.",
        ge=1,
        le=50,
    ),
]


def _industry_key(industry_name: str) -> str:
    """Converte o nome de uma indústria na chave usada pela API da Yahoo.

    Exemplo: 'Banks—Regional' -> 'banks-regional'.
    """
    normalized = industry_name.strip().lower().replace("&", " ").replace(",", " ")
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


# Chaves válidas de indústria -> nome legível, derivadas do catálogo do yfinance.
# O `SECTOR_INDUSTY_MAPPING_LC` do próprio yfinance não serve aqui porque mantém
# o travessão (—) dos nomes originais, que a API da Yahoo rejeita com HTTP 404.
INDUSTRY_KEYS: dict[str, str] = {
    _industry_key(industry): industry
    for industries in SECTOR_INDUSTY_MAPPING.values()
    for industry in industries
}


class TickerInput(BaseModel):
    """Argumentos de uma consulta por ticker."""

    ticker_name: TickerSymbol

    @field_validator("ticker_name")
    @classmethod
    def _clean(cls, value: str) -> str:
        return value.strip().upper()


class TickerNewsInput(TickerInput):
    """Argumentos da busca de notícias de um ticker."""

    count: ResultLimit = 5
    tab: Annotated[
        Literal["news", "all", "press releases"],
        Field(
            title="Tipo de conteúdo",
            description=(
                "Qual aba de notícias consultar: 'news' para notícias, "
                "'press releases' para comunicados da empresa e 'all' para ambos."
            ),
        ),
    ] = "news"


class MarketInput(BaseModel):
    """Argumentos da consulta de resumo de mercado."""

    region: MarketRegionCode = "US"


class CompanySearchInput(BaseModel):
    """Argumentos da busca de ticker pelo nome da empresa."""

    company_name: CompanyName
    count: ResultLimit = 5


class IndustrySearchInput(BaseModel):
    """Argumentos da busca de tickers por indústria."""

    industry: IndustryLabel
    count: ResultLimit = 10
    region: CountryRegionCode = "US"

    @field_validator("industry")
    @classmethod
    def _resolve_key(cls, value: str) -> str:
        """Normaliza o nome informado para uma chave de indústria válida.

        Aceita variações de escrita ('banks regional', 'Banks—Regional') e,
        quando não há correspondência exata, tenta a aproximação mais próxima.
        """
        key = _industry_key(value)
        if key in INDUSTRY_KEYS:
            return key

        matches = difflib.get_close_matches(key, INDUSTRY_KEYS, n=1, cutoff=0.6)
        if matches:
            return matches[0]

        suggestions = ", ".join(sorted(INDUSTRY_KEYS)[:10])
        raise ValueError(
            f"Indústria '{value}' não reconhecida. "
            f"Use um dos nomes da classificação da Yahoo Finance, por exemplo: {suggestions}..."
        )

    @field_validator("region")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()
