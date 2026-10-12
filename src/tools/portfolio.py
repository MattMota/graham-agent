"""Carteira e watchlist do usuário.

No Graham, as que gravam dados passam antes pelo nó de aprovação do grafo: o
usuário confirma, corrige ou cancela cada operação antes de ela chegar aqui.
Por fora, só com uma chave que tenha a permissão de escrita.
"""

import asyncio
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from src.tools import market
from src.tools.context import ToolContext, ToolFailure
from src.storage import portfolio as store



async def _quote(ticker: str) -> Optional[dict[str, Any]]:
    """Cotação atual, ou `None` se a Yahoo não a tiver.

    Chama a função por trás da ferramenta, não a ferramenta: assim a consulta
    não aparece na interface como uma ferramenta à parte.
    """
    try:
        return await asyncio.to_thread(market.get_current_stock_price, ticker)
    except Exception:  # noqa: BLE001 - sem cotação, os valores atuais ficam em branco
        return None


async def _resolve(ticker: str) -> tuple[str, str]:
    """O símbolo oficial do ativo e a moeda em que ele é cotado."""
    quote = await _quote(ticker)
    if not quote or not quote.get("currency"):
        raise ToolFailure(
            f"Ticker '{ticker}' não encontrado na Yahoo Finance. Ações brasileiras "
            "usam o sufixo '.SA'; busque o ticker pelo nome da empresa se preciso."
        )
    return quote["ticker_name"], quote["currency"]


async def _exchange_rate(source: str, target: str) -> Optional[Decimal]:
    """Quanto vale uma unidade de `source` em `target`, pelo câmbio de agora."""
    if source == target:
        return Decimal(1)
    quote = await _quote(f"{source}{target}=X")
    price = (quote or {}).get("price")
    return None if price is None else _decimal(price)


def _decimal(value: float) -> Decimal:
    # Pela string, para 0.1 não virar 0.1000000000000000055511151231257827.
    return Decimal(str(value))


def _float(value: Optional[Decimal]) -> Optional[float]:
    return None if value is None else float(value)


# Carteira ──────────────────────────────────────────────────────────────────


async def _register(
    context: ToolContext,
    side: Literal["compra", "venda"],
    ticker_name: str,
    quantity: float,
    unit_price: float,
    traded_on: date,
    currency: Optional[str],
) -> dict[str, Any]:
    pool, user_id = context.require_user()
    ticker, quote_currency = await _resolve(ticker_name)
    price_currency = currency or quote_currency
    # Sem câmbio entre as duas moedas, o valor atual nunca poderia ser calculado.
    if await _exchange_rate(quote_currency, price_currency) is None:
        raise ToolFailure(
            f"Não há câmbio de {quote_currency} para {price_currency} na Yahoo Finance; "
            "registre o preço em outra moeda."
        )
    try:
        trade, position = await store.add_trade(
            pool,
            user_id,
            ticker=ticker,
            side=side,
            quantity=_decimal(quantity),
            unit_price=_decimal(unit_price),
            price_currency=price_currency,
            quote_currency=quote_currency,
            traded_on=traded_on,
        )
    except store.PortfolioError as error:
        raise ToolFailure(str(error)) from None

    return {
        "operation": side,
        "ticker_name": ticker,
        "quantity": _float(trade["quantity"]),
        "unit_price": _float(trade["unit_price"]),
        "total": _float(trade["quantity"] * trade["unit_price"]),
        "currency": price_currency,
        "quote_currency": quote_currency,
        "traded_on": trade["traded_on"].isoformat(),
        "position": {
            "quantity": _float(position.quantity),
            "average_price": _float(position.average_price),
            "invested": _float(position.invested),
            "realized": _float(position.realized),
        },
    }


async def register_purchase(
    context: ToolContext,
    ticker_name: str,
    quantity: float,
    unit_price: float,
    traded_on: date,
    currency: Optional[str] = None,
) -> dict[str, Any]:
    return await _register(context, "compra", ticker_name, quantity, unit_price, traded_on, currency)


async def register_sale(
    context: ToolContext,
    ticker_name: str,
    quantity: float,
    unit_price: float,
    traded_on: date,
    currency: Optional[str] = None,
) -> dict[str, Any]:
    return await _register(context, "venda", ticker_name, quantity, unit_price, traded_on, currency)


async def view_portfolio(
    context: ToolContext,
    ticker_name: Optional[str] = None,
    currency: Optional[str] = None,
    include_trades: bool = False,
) -> dict[str, Any]:
    pool, user_id = context.require_user()
    trades = await store.list_trades(pool, user_id, ticker_name)
    if currency:
        trades = [trade for trade in trades if trade["price_currency"] == currency]

    positions = store.replay(trades)
    held = [position for position in positions.values() if position.quantity > 0]
    quotes = dict(zip(
        [position.ticker for position in held],
        await asyncio.gather(*(_quote(position.ticker) for position in held)),
    ))
    # Câmbio de cada par de moedas em uso, da cotação do ativo para a do custo.
    pairs = sorted({(p.quote_currency, p.currency) for p in held if p.quote_currency != p.currency})
    rates = dict(zip(pairs, await asyncio.gather(*(_exchange_rate(*pair) for pair in pairs))))

    rows = []
    totals: dict[str, dict[str, Any]] = {}
    for position in positions.values():
        total = totals.setdefault(position.currency, {
            "currency": position.currency,
            "invested": Decimal(0),
            "current_value": Decimal(0),
            "realized": Decimal(0),
            "complete": True,  # todos os ativos da moeda têm cotação
        })
        total["realized"] += position.realized
        if position.quantity == 0:
            continue

        quote = quotes.get(position.ticker) or {}
        price = quote.get("price")
        rate = rates.get((position.quote_currency, position.currency), Decimal(1))
        current_value = (
            None if price is None or rate is None else position.quantity * _decimal(price) * rate
        )
        result = None if current_value is None else current_value - position.invested

        total["invested"] += position.invested
        if current_value is None:
            total["complete"] = False
        else:
            total["current_value"] += current_value

        rows.append({
            "ticker_name": position.ticker,
            "company_name": quote.get("company_name"),
            "currency": position.currency,
            "quote_currency": position.quote_currency,
            # Presente só quando o ativo é cotado numa moeda e foi pago em outra.
            "exchange_rate": _float(rate) if position.quote_currency != position.currency else None,
            "quantity": _float(position.quantity),
            "average_price": _float(position.average_price),
            "invested": _float(position.invested),
            "current_price": price,
            "current_value": _float(current_value),
            "result": _float(result),
            "result_percent": _float(result / position.invested * 100) if result is not None else None,
            "quoted_at": quote.get("quoted_at"),
        })

    summary = []
    for total in totals.values():
        complete = total.pop("complete")
        invested, current = total["invested"], total["current_value"]
        summary.append({
            **{key: _float(value) if isinstance(value, Decimal) else value for key, value in total.items()},
            # Com algum ativo sem cotação, o valor atual da moeda não fecha.
            "current_value": _float(current) if complete else None,
            "result": _float(current - invested) if complete else None,
            "result_percent": _float((current - invested) / invested * 100) if complete and invested else None,
        })

    output: dict[str, Any] = {"positions": rows, "totals": summary}
    if include_trades:
        output["trades"] = [
            {
                "ticker_name": trade["ticker"],
                "side": trade["side"],
                "quantity": _float(trade["quantity"]),
                "unit_price": _float(trade["unit_price"]),
                "currency": trade["price_currency"],
                "traded_on": trade["traded_on"].isoformat(),
            }
            for trade in trades
        ]
    return output


# Watchlist ─────────────────────────────────────────────────────────────────


def _watch_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker_name": row["ticker"],
        "operation": row["operation"],
        "target_price": _float(row["target_price"]),
        "quantity": _float(row["quantity"]),
        "currency": row["currency"],
    }


async def add_to_watchlist(
    context: ToolContext,
    ticker_name: str,
    operation: Literal["compra", "venda", "short"],
    target_price: float,
    quantity: Optional[float] = None,
) -> dict[str, Any]:
    pool, user_id = context.require_user()
    ticker, currency = await _resolve(ticker_name)
    try:
        row = await store.add_watch(
            pool,
            user_id,
            ticker=ticker,
            operation=operation,
            target_price=_decimal(target_price),
            quantity=None if quantity is None else _decimal(quantity),
            currency=currency,
        )
    except store.PortfolioError as error:
        raise ToolFailure(str(error)) from None
    return {"added": _watch_entry(row)}


async def remove_from_watchlist(
    context: ToolContext,
    ticker_name: str,
    operation: Literal["compra", "venda", "short"],
    target_price: Optional[float] = None,
) -> dict[str, Any]:
    pool, user_id = context.require_user()
    try:
        row = await store.remove_watch(
            pool,
            user_id,
            ticker=ticker_name,
            operation=operation,
            target_price=None if target_price is None else _decimal(target_price),
        )
    except store.PortfolioError as error:
        raise ToolFailure(str(error)) from None
    return {"removed": _watch_entry(row)}


def _reached(operation: str, price: float, target: float) -> bool:
    # Compra espera o preço cair até o alvo; venda e short, subir até ele.
    return price <= target if operation == "compra" else price >= target


async def view_watchlist(context: ToolContext, ticker_name: Optional[str] = None) -> dict[str, Any]:
    pool, user_id = context.require_user()
    rows = await store.list_watch(pool, user_id, ticker_name)
    tickers = sorted({row["ticker"] for row in rows})
    quotes = dict(zip(tickers, await asyncio.gather(*(_quote(ticker) for ticker in tickers))))

    entries = []
    for row in rows:
        entry = _watch_entry(row)
        price = (quotes.get(row["ticker"]) or {}).get("price")
        target = entry["target_price"]
        entries.append({
            **entry,
            "current_price": price,
            "distance_percent": None if price is None else (price - target) / target * 100,
            "reached": None if price is None else _reached(row["operation"], price, target),
        })
    return {"entries": entries}


# Sem o tratamento, uma ToolException derrubaria o turno; com ele, a mensagem
# volta ao modelo como resposta da ferramenta, marcada como erro.
