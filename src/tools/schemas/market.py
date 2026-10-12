"""Esquemas das ferramentas de mercado.

Os tipos que elas compartilham, a entrada (os argumentos que o agente envia,
validados antes da chamada) e a saída (o que a Yahoo e o Google News devolvem,
normalizado).
"""

import difflib
import re
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from yfinance.const import SECTOR_INDUSTY_MAPPING

from src.tools.schemas.common import TickerSymbol


# Tipos ───────────────────────────────────────────────────────────────────────

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


# Entrada ─────────────────────────────────────────────────────────────────────

ResultLimit = Annotated[
    int,
    Field(
        title="Quantidade de resultados",
        description="Número máximo de resultados a retornar.",
        ge=1,
        le=50,
    ),
]


def industry_key(industry_name: str) -> str:
    """Converte o nome de uma indústria na chave usada pela API da Yahoo.

    Exemplo: 'Banks—Regional' -> 'banks-regional'.
    """
    normalized = industry_name.strip().lower().replace("&", " ").replace(",", " ")
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


# Chaves válidas de indústria -> nome legível, derivadas do catálogo do yfinance.
# O `SECTOR_INDUSTY_MAPPING_LC` do próprio yfinance não serve aqui porque mantém
# o travessão (—) dos nomes originais, que a API da Yahoo rejeita com HTTP 404.
INDUSTRY_KEYS: dict[str, str] = {
    industry_key(industry): industry
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


class TopicNewsInput(BaseModel):
    """Argumentos da busca de notícias por tema."""

    query: str = Field(
        title="Tema",
        description=(
            "Palavras-chave em português, como numa busca de notícias: o assunto e os nomes "
            "que o identificam ('privatização Banco do Brasil', 'eleições estatais', "
            "'taxa Selic Copom'). Sem frases inteiras nem tickers."
        ),
        min_length=2,
        max_length=120,
    )
    days: int = Field(
        default=30,
        title="Período em dias",
        description="Só notícias publicadas nos últimos N dias.",
        ge=1,
        le=365,
    )
    count: ResultLimit = 8

    @field_validator("query")
    @classmethod
    def _clean(cls, value: str) -> str:
        return " ".join(value.split())


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
        key = industry_key(value)
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


# Saída ───────────────────────────────────────────────────────────────────────


class StockQuote(BaseModel):
    """Cotação atual e indicadores rápidos de uma ação."""

    ticker_name: TickerSymbol
    company_name: Optional[CompanyName] = Field(
        default=None, description="Nome completo da empresa."
    )
    exchange: Optional[str] = Field(
        default=None, description="Bolsa onde a ação é negociada."
    )
    currency: Optional[str] = Field(
        default=None, description="Moeda em que o preço é cotado (ex.: 'BRL', 'USD')."
    )
    quote_type: Optional[str] = Field(
        default=None, description="Tipo do ativo (ex.: 'EQUITY', 'ETF', 'INDEX')."
    )
    price: Optional[float] = Field(
        default=None, description="Último preço negociado."
    )
    previous_close: Optional[float] = Field(
        default=None, description="Preço de fechamento do pregão anterior."
    )
    change: Optional[float] = Field(
        default=None,
        description="Variação absoluta em relação ao fechamento anterior.",
    )
    change_percent: Optional[float] = Field(
        default=None,
        description="Variação percentual em relação ao fechamento anterior.",
    )
    open: Optional[float] = Field(
        default=None, description="Preço de abertura do pregão atual."
    )
    day_high: Optional[float] = Field(
        default=None, description="Maior preço do pregão atual."
    )
    day_low: Optional[float] = Field(
        default=None, description="Menor preço do pregão atual."
    )
    volume: Optional[float] = Field(
        default=None, description="Volume negociado no último pregão."
    )
    market_cap: Optional[float] = Field(
        default=None, description="Valor de mercado da empresa."
    )
    year_high: Optional[float] = Field(
        default=None, description="Maior preço dos últimos 12 meses."
    )
    year_low: Optional[float] = Field(
        default=None, description="Menor preço dos últimos 12 meses."
    )
    year_change_percent: Optional[float] = Field(
        default=None, description="Variação percentual nos últimos 12 meses."
    )
    fifty_day_average: Optional[float] = Field(
        default=None, description="Preço médio dos últimos 50 pregões."
    )
    two_hundred_day_average: Optional[float] = Field(
        default=None, description="Preço médio dos últimos 200 pregões."
    )
    quoted_at: Optional[datetime] = Field(
        default=None, description="Momento da última atualização da cotação."
    )
    timezone: Optional[str] = Field(
        default=None, description="Fuso horário da bolsa."
    )


class MarketIndexQuote(BaseModel):
    """Cotação de um índice/ativo que compõe o resumo de mercado."""

    ticker_name: TickerSymbol
    name: Optional[str] = Field(default=None, description="Nome do índice ou ativo.")
    exchange: Optional[str] = Field(default=None, description="Bolsa de origem.")
    price: Optional[float] = Field(default=None, description="Preço atual.")
    previous_close: Optional[float] = Field(
        default=None, description="Fechamento anterior."
    )
    change: Optional[float] = Field(default=None, description="Variação absoluta.")
    change_percent: Optional[float] = Field(
        default=None, description="Variação percentual."
    )
    market_state: Optional[str] = Field(
        default=None,
        description="Estado da negociação (ex.: 'REGULAR', 'CLOSED', 'PRE', 'POST').",
    )


class MarketSummary(BaseModel):
    """Resumo do mercado de uma região."""

    region: MarketRegionCode
    status: Optional[str] = Field(
        default=None,
        description="Situação do mercado (ex.: 'open', 'closed'). Disponível apenas para a região 'US'.",
    )
    status_message: Optional[str] = Field(
        default=None, description="Descrição da situação do mercado."
    )
    opens_at: Optional[datetime] = Field(
        default=None, description="Horário de abertura do pregão."
    )
    closes_at: Optional[datetime] = Field(
        default=None, description="Horário de fechamento do pregão."
    )
    quotes: list[MarketIndexQuote] = Field(
        default_factory=list,
        description="Cotações dos principais índices/ativos da região.",
    )


class NewsArticle(BaseModel):
    """Notícia publicada sobre um ticker ou um tema."""

    title: Optional[str] = Field(default=None, description="Título da notícia.")
    summary: Optional[str] = Field(default=None, description="Resumo da notícia.")
    published_at: Optional[datetime] = Field(
        default=None, description="Data e hora de publicação."
    )
    link: Optional[str] = Field(default=None, description="Link para a notícia.")
    publisher: Optional[str] = Field(
        default=None, description="Veículo que publicou a notícia."
    )


class TickerNews(BaseModel):
    """Últimas notícias de um ticker."""

    ticker_name: TickerSymbol
    articles: list[NewsArticle] = Field(
        default_factory=list, description="Notícias encontradas, da mais recente à mais antiga."
    )
    note: Optional[str] = Field(
        default=None, description="Como as notícias foram encontradas, quando isso muda a leitura."
    )


class TopicNews(BaseModel):
    """Notícias encontradas pela busca de um tema."""

    query: str = Field(description="O tema buscado.")
    days: int = Field(description="Período da busca, em dias.")
    articles: list[NewsArticle] = Field(
        default_factory=list,
        description="Notícias mais relevantes, da mais recente à mais antiga.",
    )
    note: Optional[str] = Field(default=None, description="Como ler as notícias.")


class CompanyMatch(BaseModel):
    """Empresa encontrada na busca por nome."""

    ticker_name: TickerSymbol
    company_name: Optional[CompanyName] = Field(
        default=None, description="Nome completo da empresa."
    )
    short_name: Optional[str] = Field(
        default=None, description="Nome abreviado usado pela bolsa."
    )
    exchange: Optional[str] = Field(
        default=None, description="Bolsa onde o ativo é negociado."
    )
    quote_type: Optional[str] = Field(
        default=None, description="Tipo do ativo (ex.: 'EQUITY', 'ETF')."
    )
    sector: Optional[str] = Field(default=None, description="Setor da empresa.")
    industry: Optional[IndustryLabel] = Field(
        default=None, description="Indústria (subsetor) da empresa."
    )


class CompanySearchResults(BaseModel):
    """Resultado da busca de tickers pelo nome da empresa."""

    query: CompanyName
    matches: list[CompanyMatch] = Field(
        default_factory=list, description="Empresas encontradas, da mais relevante à menos relevante."
    )


class IndustryCompany(BaseModel):
    """Empresa listada dentro de uma indústria."""

    ticker_name: TickerSymbol
    company_name: Optional[CompanyName] = Field(
        default=None, description="Nome da empresa."
    )
    rating: Optional[str] = Field(
        default=None,
        description="Recomendação média dos analistas (ex.: 'Buy', 'Hold').",
    )
    market_weight: Optional[float] = Field(
        default=None,
        description="Peso da empresa dentro da indústria (fração de 0 a 1).",
    )


class IndustryCompanies(BaseModel):
    """Principais empresas de uma indústria."""

    industry_key: Annotated[
        str, Field(description="Chave da indústria usada na consulta à Yahoo Finance.")
    ]
    industry_name: Optional[IndustryLabel] = Field(
        default=None, description="Nome da indústria."
    )
    sector_name: Optional[str] = Field(
        default=None, description="Setor ao qual a indústria pertence."
    )
    region: Optional[str] = Field(
        default=None, description="País usado para filtrar as empresas listadas."
    )
    companies_count: Optional[int] = Field(
        default=None, description="Total de empresas na indústria."
    )
    companies: list[IndustryCompany] = Field(
        default_factory=list,
        description="Principais empresas da indústria, da maior para a menor participação.",
    )
