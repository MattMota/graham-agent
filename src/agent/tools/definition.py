"""Ferramentas do agente — wrappers sobre a API do yfinance."""
import inspect, math, sys
from langchain_core.tools import BaseTool

from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

import pandas as pd
import yfinance as yf
from langchain_core.tools import tool

from src.agent.tools.schemas.input import (
    INDUSTRY_KEYS,
    CompanySearchInput,
    IndustrySearchInput,
    TickerInput,
    TickerNewsInput,
)
from src.agent.tools.schemas.output import (
    CompanyMatch,
    CompanySearchResults,
    IndustryCompanies,
    IndustryCompany,
    NewsArticle,
    StockQuote,
    TickerNews,
)


def _ticker(ticker_name: str) -> yf.Ticker:
    """Instancia um `yf.Ticker`, traduzindo falhas de formato em erro legível."""
    try:
        return yf.Ticker(ticker_name)
    except ValueError as error:
        raise ValueError(f"Ticker '{ticker_name}' inválido: {error}") from error


def _safe(getter: Callable[[], Any]) -> Optional[Any]:
    """Retorna o valor buscado ou `None` quando o dado não existe na Yahoo."""
    try:
        value = getter()
    except Exception:
        return None
    # A Yahoo devolve NaN onde o dado não se aplica — BTC-USD não tem
    # fechamento anterior, por exemplo. Para o Python NaN é um float válido,
    # e ele contaminaria as contas e o JSON; aqui vira ausência de dado.
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _percent_change(price: Optional[float], previous: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    """Calcula a variação absoluta e percentual em relação ao fechamento anterior."""
    if price is None or not previous:
        return None, None
    change = price - previous
    return change, change / previous * 100


def _cell(row: "pd.Series", column: str) -> Optional[Any]:
    """Lê uma célula de um DataFrame do yfinance, tratando NaN como ausência de dado."""
    value = row.get(column)
    return None if value is None or pd.isna(value) else value


def _timestamp(value: Optional[Any]) -> Optional[datetime]:
    """Normaliza uma data do yfinance (epoch em segundos ou Timestamp) para `datetime`."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return pd.Timestamp(value).to_pydatetime()


@tool(
    "cotacao_atual_acao",
    description=(
        "Retorna a cotação atual e os indicadores rápidos de uma ação a partir do seu ticker: "
        "nome da empresa, preço, variação do dia, abertura, máxima e mínima, volume, "
        "valor de mercado, máxima e mínima de 52 semanas e médias móveis. "
        "Use quando o usuário perguntar quanto vale uma ação ou como ela está se comportando hoje."
    ),
    args_schema=TickerInput,
)
def get_current_stock_price(ticker_name: str) -> dict[str, Any]:
    ticker = _ticker(ticker_name)
    fast_info = ticker.get_fast_info()

    price = _safe(lambda: fast_info["lastPrice"])
    if price is None:
        raise ValueError(
            f"Nenhum dado encontrado para o ticker '{ticker_name}'. "
            "Verifique o código (ações brasileiras usam o sufixo '.SA') "
            "ou busque o ticker pelo nome da empresa."
        )

    # Já carregado pela chamada anterior: é de onde vem o nome da empresa,
    # que o `fast_info` não expõe.
    metadata = ticker.get_history_metadata() or {}

    previous_close = _safe(lambda: fast_info["regularMarketPreviousClose"]) or _safe(
        lambda: fast_info["previousClose"]
    )
    change, change_percent = _percent_change(price, previous_close)
    year_change = _safe(lambda: fast_info["yearChange"])

    quote = StockQuote(
        ticker_name=metadata.get("symbol") or ticker_name,
        company_name=metadata.get("longName") or metadata.get("shortName"),
        exchange=metadata.get("fullExchangeName") or _safe(lambda: fast_info["exchange"]),
        currency=_safe(lambda: fast_info["currency"]),
        quote_type=_safe(lambda: fast_info["quoteType"]),
        price=price,
        previous_close=previous_close,
        change=change,
        change_percent=change_percent,
        open=_safe(lambda: fast_info["open"]),
        day_high=_safe(lambda: fast_info["dayHigh"]),
        day_low=_safe(lambda: fast_info["dayLow"]),
        volume=_safe(lambda: fast_info["lastVolume"]),
        market_cap=_safe(lambda: fast_info["marketCap"]),
        year_high=_safe(lambda: fast_info["yearHigh"]),
        year_low=_safe(lambda: fast_info["yearLow"]),
        year_change_percent=None if year_change is None else year_change * 100,
        fifty_day_average=_safe(lambda: fast_info["fiftyDayAverage"]),
        two_hundred_day_average=_safe(lambda: fast_info["twoHundredDayAverage"]),
        quoted_at=_timestamp(metadata.get("regularMarketTime")),
        timezone=_safe(lambda: fast_info["timezone"]),
    )
    return quote.model_dump(mode="json")


@tool(
    "noticias_acao",
    description=(
        "Retorna as últimas notícias publicadas sobre uma ação, com título, resumo, "
        "data de publicação e link. Use quando o usuário quiser saber o que está sendo "
        "noticiado sobre uma empresa ou o que explica um movimento recente do papel."
    ),
    args_schema=TickerNewsInput,
)
def get_ticker_news(
    ticker_name: str,
    count: int = 5,
    tab: Literal["news", "all", "press releases"] = "news",
) -> dict[str, Any]:
    articles = []
    for item in _ticker(ticker_name).get_news(count=count, tab=tab):
        # Cada item vem como {'id': ..., 'content': {...}}; os campos úteis
        # ficam dentro de 'content'.
        content = item.get("content") or item
        # Só um dos dois links costuma vir preenchido.
        link = (content.get("canonicalUrl") or {}).get("url") or (
            content.get("clickThroughUrl") or {}
        ).get("url")

        articles.append(
            NewsArticle(
                title=content.get("title"),
                summary=content.get("summary") or content.get("description"),
                published_at=content.get("pubDate") or content.get("displayTime"),
                link=link,
                publisher=(content.get("provider") or {}).get("displayName"),
            )
        )

    news = TickerNews(ticker_name=ticker_name, articles=articles)
    return news.model_dump(mode="json")


@tool(
    "buscar_ticker_por_empresa",
    description=(
        "Busca os tickers correspondentes ao nome de uma empresa, retornando código, nome, "
        "bolsa, setor e indústria de cada resultado. Use quando o usuário citar a empresa pelo "
        "nome ('Banco do Brasil', 'Petrobras') e for preciso descobrir o ticker antes de "
        "consultar cotação ou notícias."
    ),
    args_schema=CompanySearchInput,
)
def find_ticker_by_company(company_name: str, count: int = 5) -> dict[str, Any]:
    search = yf.Search(
        company_name,
        max_results=count,
        news_count=0,
        lists_count=0,
        enable_fuzzy_query=True,
    )

    matches = [
        CompanyMatch(
            ticker_name=quote["symbol"],
            company_name=quote.get("longname") or quote.get("shortname"),
            short_name=quote.get("shortname"),
            exchange=quote.get("exchDisp") or quote.get("exchange"),
            quote_type=quote.get("quoteType"),
            sector=quote.get("sector"),
            industry=quote.get("industry"),
        )
        for quote in search.quotes[:count]
    ]

    results = CompanySearchResults(query=company_name, matches=matches)
    return results.model_dump(mode="json")


@tool(
    "buscar_tickers_por_industria",
    description=(
        "Lista as principais empresas de uma indústria (subsetor) da classificação da Yahoo Finance, "
        "com ticker, nome, recomendação dos analistas e peso dentro da indústria. "
        "Exemplos de indústria: 'Banks - Regional', 'Software - Application', 'Oil & Gas E&P'. "
        "Aceita variações de escrita do nome. Use o parâmetro 'region' para filtrar por país "
        "(ex.: 'BR' para empresas brasileiras). Use para comparar concorrentes ou encontrar "
        "empresas de um mesmo segmento."
    ),
    args_schema=IndustrySearchInput,
)
def find_tickers_by_industry(
    industry: str, count: int = 10, region: str = "US"
) -> dict[str, Any]:
    # `industry` já chega normalizado como chave válida pelo IndustrySearchInput.
    domain = yf.Industry(industry, region=region)
    top_companies = domain.top_companies

    companies = []
    if top_companies is not None:
        for symbol, row in top_companies.head(count).iterrows():
            companies.append(
                IndustryCompany(
                    ticker_name=symbol,
                    company_name=_cell(row, "name"),
                    rating=_cell(row, "rating"),
                    market_weight=_cell(row, "market weight"),
                )
            )

    result = IndustryCompanies(
        industry_key=industry,
        industry_name=domain.name or INDUSTRY_KEYS.get(industry),
        sector_name=domain.sector_name,
        region=region,
        companies_count=(domain.overview or {}).get("companies_count"),
        companies=companies,
    )
    return result.model_dump(mode="json")

TOOLS = [
    obj
    for _, obj in inspect.getmembers(
        sys.modules[__name__],
        predicate = lambda o: isinstance(o, BaseTool)
    )
]
