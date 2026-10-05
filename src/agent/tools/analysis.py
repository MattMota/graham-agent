"""Ferramentas de análise: proventos de um ativo ou da carteira, e desempenho."""

import asyncio
import calendar
import inspect
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from langchain_core.tools import BaseTool, ToolException, tool
from langgraph.prebuilt import ToolRuntime

from src.agent.runtime.context import AgentContext
from src.agent.tools import definition as market
from src.agent.tools.portfolio import _context as require_context
from src.agent.tools.schemas.analysis import IncomeInput, PerformanceInput
from src.storage import portfolio as store
from src.storage.cache import cached

# Proventos mudam pouco ao longo do dia; o histórico de preços, a cada pregão.
INCOME_TTL = 24 * 60 * 60
HISTORY_TTL = 60 * 60

# Pontos por série no gráfico. A série vai só para a interface, nunca para o
# modelo, mas não precisa de mais resolução do que a tela mostra.
MAX_CHART_POINTS = 260

INDEXES = {"^BVSP": "Ibovespa", "^GSPC": "S&P 500"}

INCOME_NOTE = (
    "Valores brutos por ação ou cota, antes de impostos, na data ex: tem direito quem "
    "tinha o ativo no fim do pregão anterior a ela."
)

PERFORMANCE_NOTE = (
    "O retorno com proventos supõe que eles foram reinvestidos no próprio ativo. Cada "
    "ativo está na moeda da própria cotação."
)


def _months_ago(months: int) -> date:
    today = date.today()
    month = today.month - months
    year = today.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    return None if value is None or not math.isfinite(value) else round(value, digits)


# Proventos ─────────────────────────────────────────────────────────────────


# Sem proventos pode ser um ativo que não paga (um ETF) ou a fonte fora do ar;
# nos dois casos, não fica no cache.
@cached("proventos", ttl=INCOME_TTL, keep=lambda result: bool(result["payments"]))
def _dividend_data(ticker: str) -> dict[str, Any]:
    """Todos os proventos registrados na Yahoo, pela data ex, e a próxima data ex."""
    yf_ticker = market._ticker(ticker)
    series = market._safe(lambda: yf_ticker.dividends)
    payments = []
    if series is not None:
        for stamp, amount in series.items():
            if amount and math.isfinite(amount):
                payments.append({"ex_date": stamp.date().isoformat(), "amount": float(amount)})

    events = market._safe(lambda: yf_ticker.calendar) or {}
    next_ex = events.get("Ex-Dividend Date") if isinstance(events, dict) else None
    return {
        "ticker": ticker,
        "currency": market._safe(lambda: yf_ticker.fast_info["currency"]),
        "payments": payments,
        "next_ex_date": next_ex.isoformat() if isinstance(next_ex, date) else None,
    }


def _received(ticker: str, trades: list[dict], payments: list[dict]) -> list[dict[str, Any]]:
    """Quanto a carteira recebeu em cada pagamento.

    Tem direito quem tinha o ativo no fim do pregão anterior à data ex, então
    entram só as operações feitas antes dela.
    """
    rows = []
    for payment in payments:
        before = [trade for trade in trades if trade["traded_on"].isoformat() < payment["ex_date"]]
        position = store.replay(before).get(ticker)
        quantity = float(position.quantity) if position else 0.0
        if quantity > 0:
            rows.append({
                "ex_date": payment["ex_date"],
                "amount": _round(payment["amount"], 6),
                "quantity": quantity,
                "received": _round(quantity * payment["amount"], 2),
            })
    return rows


async def _asset_income(runtime: ToolRuntime, ticker: str, since: date, months: int) -> dict[str, Any]:
    data, quote = await asyncio.gather(
        asyncio.to_thread(_dividend_data, ticker),
        asyncio.to_thread(market._safe, lambda: market.get_current_stock_price.func(ticker)),
    )
    payments = data["payments"]
    window = [p for p in payments if p["ex_date"] >= since.isoformat()]
    trailing = [p for p in payments if p["ex_date"] >= _months_ago(12).isoformat()]
    trailing_total = sum(p["amount"] for p in trailing)
    price = (quote or {}).get("price")
    next_ex = data["next_ex_date"]

    output: dict[str, Any] = {
        "ticker_name": ticker,
        "currency": data["currency"],
        "months": months,
        "payments": [
            {"ex_date": p["ex_date"], "amount": _round(p["amount"], 6)} for p in reversed(window)
        ],
        "total_in_window": _round(sum(p["amount"] for p in window), 6),
        "trailing_12m_total": _round(trailing_total, 6),
        "price": price,
        # Sem nenhum provento registrado (um ETF que não distribui), não há yield a calcular.
        "dividend_yield_12m": _round(trailing_total / price * 100, 2) if price and payments else None,
        "next_ex_date": next_ex if next_ex and next_ex >= date.today().isoformat() else None,
        "note": INCOME_NOTE if payments else "A Yahoo não tem registro de proventos deste ativo.",
    }

    # Se o usuário tem ou teve o ativo, quanto ele recebeu na mesma janela.
    context = getattr(runtime, "context", None)
    if isinstance(context, AgentContext):
        trades = await store.list_trades(context.pool, context.user_id, ticker)
        rows = _received(ticker, trades, window) if trades else []
        if rows:
            output["your_income"] = {
                "total": _round(sum(row["received"] for row in rows), 2),
                "payments": list(reversed(rows)),
            }
    return output


async def _portfolio_income(context: AgentContext, since: date, months: int) -> dict[str, Any]:
    trades = await store.list_trades(context.pool, context.user_id)
    if not trades:
        return {"months": months, "assets": [], "totals": [], "upcoming": [], "note": "A carteira não tem operações."}

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        by_ticker[trade["ticker"]].append(trade)
    fetched = await asyncio.gather(
        *(asyncio.to_thread(_dividend_data, ticker) for ticker in by_ticker), return_exceptions=True
    )

    assets, upcoming, missing = [], [], []
    totals: dict[str, float] = defaultdict(float)
    for (ticker, ticker_trades), data in zip(by_ticker.items(), fetched):
        if isinstance(data, Exception):
            missing.append(ticker)
            continue
        window = [p for p in data["payments"] if p["ex_date"] >= since.isoformat()]
        rows = _received(ticker, ticker_trades, window)
        currency = data["currency"] or ticker_trades[0]["quote_currency"]
        if rows:
            total = sum(row["received"] for row in rows)
            totals[currency] += total
            assets.append({
                "ticker_name": ticker,
                "currency": currency,
                "total": _round(total, 2),
                "payments": list(reversed(rows)),
            })

        held = store.replay(ticker_trades).get(ticker)
        next_ex = data["next_ex_date"]
        if held and held.quantity > 0 and next_ex and next_ex >= date.today().isoformat():
            upcoming.append({"ticker_name": ticker, "next_ex_date": next_ex, "quantity": float(held.quantity)})

    output: dict[str, Any] = {
        "months": months,
        "assets": sorted(assets, key=lambda asset: asset["total"] or 0, reverse=True),
        "totals": [{"currency": currency, "total": _round(total, 2)} for currency, total in totals.items()],
        "upcoming": sorted(upcoming, key=lambda item: item["next_ex_date"]),
        "note": INCOME_NOTE,
    }
    if missing:
        output["unavailable"] = missing
    return output


@tool(
    "proventos",
    description=(
        "Mostra os proventos (dividendos, JCP, rendimentos de FIIs) de um ativo: pagamentos "
        "na janela pedida, total dos últimos 12 meses, dividend yield e a próxima data ex; se "
        "o usuário tem o ativo, também quanto ele recebeu. Sem ticker, calcula quanto a "
        "carteira do usuário recebeu, pela quantidade que ele tinha em cada data ex."
    ),
    args_schema=IncomeInput,
)
async def income(
    runtime: ToolRuntime, ticker_name: Optional[str] = None, months: int = 12
) -> dict[str, Any]:
    since = _months_ago(months)
    if ticker_name:
        return await _asset_income(runtime, ticker_name, since, months)
    return await _portfolio_income(require_context(runtime), since, months)


# Desempenho ────────────────────────────────────────────────────────────────


@cached("historico", ttl=HISTORY_TTL, keep=lambda result: bool(result["dates"]))
def _price_history(ticker: str, period: Optional[str], start: Optional[str]) -> dict[str, Any]:
    """Fechamentos diários, com e sem o ajuste por proventos e desdobramentos."""
    yf_ticker = market._ticker(ticker)
    if start:
        frame = yf_ticker.history(start=start, auto_adjust=False, actions=False)
    else:
        frame = yf_ticker.history(period=period, auto_adjust=False, actions=False)
    frame = frame.dropna(subset=["Close"]) if "Close" in frame else frame.iloc[0:0]

    closes = [float(value) for value in frame.get("Close", [])]
    adjusted = frame["Adj Close"] if "Adj Close" in frame else frame.get("Close", [])
    # Sem o fechamento ajustado de um dia, vale o fechamento do próprio dia.
    adjusted = [
        float(adj) if adj is not None and math.isfinite(adj) else close
        for adj, close in zip(adjusted, closes)
    ]
    return {
        "ticker": ticker,
        "currency": market._safe(lambda: yf_ticker.fast_info["currency"]),
        "dates": [stamp.date().isoformat() for stamp in frame.index],
        "close": closes,
        "adj_close": adjusted,
    }


def _metrics(history: dict[str, Any]) -> dict[str, Any]:
    """Retornos, volatilidade e maior queda de uma série de fechamentos."""
    dates, close, adj = history["dates"], history["close"], history["adj_close"]
    days = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
    total_return = adj[-1] / adj[0] - 1

    returns = [math.log(adj[i] / adj[i - 1]) for i in range(1, len(adj)) if adj[i - 1] > 0 and adj[i] > 0]
    # Observações por ano da própria série: cripto negocia todos os dias; a B3, não.
    per_year = len(returns) / (days / 365) if days > 0 else 252
    volatility = statistics.stdev(returns) * math.sqrt(per_year) if len(returns) > 1 else None

    peak, peak_index, drawdown, drawdown_peak, drawdown_trough = adj[0], 0, 0.0, 0, 0
    for index, value in enumerate(adj):
        if value > peak:
            peak, peak_index = value, index
        if value / peak - 1 < drawdown:
            drawdown, drawdown_peak, drawdown_trough = value / peak - 1, peak_index, index

    high = max(range(len(close)), key=close.__getitem__)
    low = min(range(len(close)), key=close.__getitem__)
    return {
        "currency": history["currency"],
        "from": dates[0],
        "to": dates[-1],
        "start_price": _round(close[0]),
        "end_price": _round(close[-1]),
        "price_return_percent": _round((close[-1] / close[0] - 1) * 100, 2),
        "total_return_percent": _round(total_return * 100, 2),
        "annualized_return_percent": _round(((1 + total_return) ** (365 / days) - 1) * 100, 2)
        if days >= 365 else None,
        "annualized_volatility_percent": _round(volatility * 100, 2) if volatility else None,
        "max_drawdown_percent": _round(drawdown * 100, 2),
        "max_drawdown_from": dates[drawdown_peak],
        "max_drawdown_to": dates[drawdown_trough],
        "high": {"price": _round(close[high]), "date": dates[high]},
        "low": {"price": _round(close[low]), "date": dates[low]},
    }


def _chart_points(history: dict[str, Any]) -> list[list[Any]]:
    """Retorno acumulado com proventos, em %, reduzido ao que o gráfico precisa."""
    dates, adj = history["dates"], history["adj_close"]
    step = max(1, math.ceil(len(dates) / MAX_CHART_POINTS))
    indexes = list(range(0, len(dates), step))
    if indexes[-1] != len(dates) - 1:
        indexes.append(len(dates) - 1)
    return [[dates[i], round((adj[i] / adj[0] - 1) * 100, 3)] for i in indexes]


@tool(
    "desempenho",
    description=(
        "Compara o desempenho de até 4 ativos num período ou desde uma data (como a da "
        "compra): retorno com e sem proventos, retorno anualizado, volatilidade, maior queda, "
        "máxima e mínima, contra o Ibovespa ou o S&P 500. A interface mostra um gráfico. Use "
        "quando o usuário perguntar como um ativo evoluiu ou se foi melhor que outro."
    ),
    args_schema=PerformanceInput,
    # O modelo recebe as métricas; a série de pontos vai à parte, só para o
    # gráfico da interface, sem gastar tokens.
    response_format="content_and_artifact",
)
async def performance(
    tickers: list[str],
    period: str = "1y",
    start_date: Optional[date] = None,
    compare_index: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    symbols = list(dict.fromkeys(tickers))
    index = None
    if compare_index:
        index = "^BVSP" if any(symbol.endswith(".SA") for symbol in symbols) else "^GSPC"
        if index in symbols:
            index = None
    start = start_date.isoformat() if start_date else None

    wanted = [*symbols, *([index] if index else [])]
    histories = await asyncio.gather(
        *(asyncio.to_thread(_price_history, symbol, None if start else period, start) for symbol in wanted),
        return_exceptions=True,
    )

    series, points, failed = [], [], []
    for symbol, history in zip(wanted, histories):
        if isinstance(history, Exception) or len(history["dates"]) < 2:
            failed.append(symbol)
            continue
        label = INDEXES.get(symbol, symbol)
        series.append({"ticker_name": symbol, "label": label, "is_index": symbol == index, **_metrics(history)})
        points.append({"ticker": symbol, "label": label, "is_index": symbol == index, "points": _chart_points(history)})

    if not any(not item["is_index"] for item in series):
        raise ToolException(
            f"Sem histórico de preços para {', '.join(symbols)} nesse período. Ações brasileiras "
            "usam o sufixo '.SA'; busque o ticker pelo nome da empresa se preciso."
        )

    content: dict[str, Any] = {
        "requested": {"period": None if start else period, "start_date": start},
        "series": series,
        "note": PERFORMANCE_NOTE,
    }
    if failed:
        content["unavailable"] = failed
    return content, {"series": points}


TOOLS: list[BaseTool] = [
    obj
    for _, obj in inspect.getmembers(sys.modules[__name__], lambda o: isinstance(o, BaseTool))
]
# A ToolException volta ao modelo como resposta da ferramenta, marcada como erro.
for _tool in TOOLS:
    _tool.handle_tool_error = True
