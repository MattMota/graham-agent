"""Ferramentas de análise: proventos de um ativo ou da carteira, desempenho e
agenda de eventos."""

import asyncio
import calendar
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.tools import market
from src.tools.context import ToolContext, ToolFailure
from src.storage import portfolio as store
from src.storage.cache import cached

# Proventos mudam pouco ao longo do dia; o histórico de preços, a cada pregão.
INCOME_TTL = 24 * 60 * 60
HISTORY_TTL = 60 * 60
# Uma data ex pode ser anunciada para o dia seguinte; algumas horas bastam.
EVENTS_TTL = 6 * 60 * 60

# Pontos por série no gráfico. A série vai só para a interface, nunca para o
# modelo, mas não precisa de mais resolução do que a tela mostra.
MAX_CHART_POINTS = 260

INDEXES = {"^BVSP": "Ibovespa", "^GSPC": "S&P 500"}

INCOME_NOTE = (
    "Valores brutos por ação ou cota, antes de impostos, na data ex: tem direito quem "
    "tinha o ativo no fim do pregão anterior a ela."
)

AGENDA_NOTE = (
    "Datas da Yahoo Finance, a partir de hoje. `resultado` é a divulgação do balanço; "
    "`estimated` marca uma data que a empresa ainda não confirmou, e `until`, o fim da janela "
    "prevista. Na `data_ex`, tem direito ao provento quem tinha o ativo no fim do pregão "
    "anterior. A Yahoo só tem a data ex depois que o provento é anunciado, a data de pagamento "
    "só para alguns ativos (em geral, os americanos) e nem sempre o próximo resultado das "
    "empresas brasileiras: um ativo em `without_events` pode ter eventos que ainda não "
    "chegaram à fonte."
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


# Eventos ───────────────────────────────────────────────────────────────────


def _zone(name: Optional[str]) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name) if name else timezone.utc
    except ZoneInfoNotFoundError:
        return timezone.utc


# Um ativo que a Yahoo não conhece não fica no cache: pode ser a fonte fora do ar.
@cached("eventos", ttl=EVENTS_TTL, keep=lambda result: result["found"])
def _events(ticker: str) -> dict[str, Any]:
    """As próximas datas do ativo na Yahoo: resultado, data ex e pagamento.

    Lidas do `info`, não do `calendar`: o yfinance converte as datas do
    `calendar` pelo fuso da máquina, e a Yahoo grava as de proventos à
    meia-noite UTC. Num servidor no Brasil, a data ex sairia um dia antes.
    """
    info = market._safe(lambda: market._ticker(ticker).get_info()) or {}

    def day(field: str) -> Optional[str]:
        # Proventos: um dia, gravado à meia-noite UTC.
        stamp = info.get(field)
        if not isinstance(stamp, (int, float)):
            return None
        return datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()

    zone = _zone(info.get("exchangeTimezoneName"))

    def local(field: str) -> Optional[str]:
        # Resultados: um instante, lido no fuso da bolsa.
        stamp = info.get(field)
        if not isinstance(stamp, (int, float)):
            return None
        return datetime.fromtimestamp(stamp, zone).date().isoformat()

    return {
        "found": bool(info.get("quoteType")),
        "ex_date": day("exDividendDate"),
        "payment_date": day("dividendDate"),
        "earnings_from": local("earningsTimestampStart"),
        "earnings_to": local("earningsTimestampEnd"),
        "earnings_estimated": bool(info.get("isEarningsDateEstimate")),
    }


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

    return {
        "ticker": ticker,
        "currency": market._safe(lambda: yf_ticker.fast_info["currency"]),
        "payments": payments,
        "next_ex_date": _events(ticker)["ex_date"],
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


async def _asset_income(context: ToolContext, ticker: str, since: date, months: int) -> dict[str, Any]:
    data, quote = await asyncio.gather(
        asyncio.to_thread(_dividend_data, ticker),
        asyncio.to_thread(market._safe, lambda: market.get_current_stock_price(ticker)),
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
    if context.has_user:
        trades = await store.list_trades(context.pool, context.user_id, ticker)
        rows = _received(ticker, trades, window) if trades else []
        if rows:
            output["your_income"] = {
                "total": _round(sum(row["received"] for row in rows), 2),
                "payments": list(reversed(rows)),
            }
    return output


async def _portfolio_income(context: ToolContext, since: date, months: int) -> dict[str, Any]:
    pool, user_id = context.require_user()
    trades = await store.list_trades(pool, user_id)
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


async def income(
    context: ToolContext, ticker_name: Optional[str] = None, months: int = 12
) -> dict[str, Any]:
    since = _months_ago(months)
    if ticker_name:
        return await _asset_income(context, ticker_name, since, months)
    return await _portfolio_income(context, since, months)


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


async def performance(
    context: ToolContext,
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
        raise ToolFailure(
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


# Agenda ────────────────────────────────────────────────────────────────────


def _dated(data: dict[str, Any], start: str, end: str) -> list[dict[str, Any]]:
    """Os eventos de um ativo que caem entre `start` e `end`, inclusive."""
    found = []
    first, last = data["earnings_from"], data["earnings_to"] or data["earnings_from"]
    # A janela de um resultado não confirmado pode ter começado antes de hoje.
    if first and last >= start and first <= end:
        event: dict[str, Any] = {"date": first, "type": "resultado", "estimated": data["earnings_estimated"]}
        if last != first:
            event["until"] = last
        found.append(event)
    for field, kind in (("ex_date", "data_ex"), ("payment_date", "pagamento")):
        if data[field] and start <= data[field] <= end:
            found.append({"date": data[field], "type": kind})
    return found


async def agenda(
    context: ToolContext, tickers: Optional[list[str]] = None, days: int = 90
) -> dict[str, Any]:
    start = date.today()
    end = start + timedelta(days=days)
    if not tickers:
        context.require_user()

    # Posições em aberto, com a quantidade, e a watchlist: a origem de cada ativo.
    held: dict[str, float] = {}
    watched: set[str] = set()
    if context.has_user:
        trades, watch = await asyncio.gather(
            store.list_trades(context.pool, context.user_id),
            store.list_watch(context.pool, context.user_id),
        )
        held = {
            ticker: float(position.quantity)
            for ticker, position in store.replay(trades).items()
            if position.quantity > 0
        }
        watched = {row["ticker"] for row in watch}

    symbols = list(dict.fromkeys(tickers)) if tickers else sorted(held.keys() | watched)
    output: dict[str, Any] = {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "days": days,
        "tickers": symbols,
        "events": [],
        "without_events": [],
        "note": AGENDA_NOTE,
    }
    if not symbols:
        output["note"] = "A carteira e a watchlist estão vazias."
        return output

    fetched = await asyncio.gather(
        *(asyncio.to_thread(_events, symbol) for symbol in symbols), return_exceptions=True
    )
    events, missing = [], []
    for symbol, data in zip(symbols, fetched):
        if isinstance(data, Exception) or not data["found"]:
            missing.append(symbol)
            continue
        dated = _dated(data, start.isoformat(), end.isoformat())
        if not dated:
            output["without_events"].append(symbol)
            continue
        origin = [name for name, present in (("carteira", symbol in held), ("watchlist", symbol in watched)) if present]
        for event in dated:
            event["ticker_name"] = symbol
            if origin:
                event["origin"] = origin
            if symbol in held:
                event["quantity"] = held[symbol]
            events.append(event)

    if tickers and len(missing) == len(symbols):
        raise ToolFailure(
            f"A Yahoo não tem dados de {', '.join(symbols)}. Ações brasileiras usam o sufixo "
            "'.SA'; busque o ticker pelo nome da empresa se preciso."
        )
    output["events"] = sorted(events, key=lambda event: (event["date"], event["ticker_name"]))
    if missing:
        output["unavailable"] = missing
    return output
