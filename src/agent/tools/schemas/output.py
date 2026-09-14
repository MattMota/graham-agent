"""Schemas de saída (retorno) das ferramentas do agente."""

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, Field

from src.agent.tools.schemas import (
    CompanyName,
    IndustryLabel,
    MarketRegionCode,
    TickerSymbol,
)


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
    """Notícia publicada sobre um ticker."""

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
