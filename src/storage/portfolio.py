"""Carteira (livro de operações) e watchlist do usuário, no schema `core`."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from psycopg import errors
from psycopg_pool import AsyncConnectionPool

from src.storage.conversations import Row

Side = Literal["compra", "venda"]
Operation = Literal["compra", "venda", "short"]

ZERO = Decimal(0)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class PortfolioError(Exception):
    """Uma operação recusada por regra da carteira; a mensagem vai ao usuário."""


# Posição ───────────────────────────────────────────────────────────────────


@dataclass
class Position:
    """O estado de um ativo depois de aplicadas as operações, em ordem."""

    ticker: str
    # Moeda do custo: a que o usuário pagou. O valor atual é convertido para ela.
    currency: str
    # Moeda em que a Yahoo cota o ativo.
    quote_currency: str
    quantity: Decimal = ZERO
    average_price: Decimal = ZERO
    # Resultado das vendas já feitas, medido contra o preço médio.
    realized: Decimal = ZERO

    @property
    def invested(self) -> Decimal:
        return self.quantity * self.average_price


def replay(trades: list[Row]) -> dict[str, Position]:
    """Aplica as operações em ordem e devolve a posição de cada ativo.

    Usa o preço médio, o critério da Receita e da B3: uma compra recalcula a
    média ponderada; uma venda reduz a quantidade sem mexer nela. Recusa a
    sequência se alguma venda deixar a posição negativa naquela data.
    """
    positions: dict[str, Position] = {}
    # Sem `created_at`, a operação ainda não foi gravada: vem por último no dia.
    # O booleano decide antes da data, que pode faltar e não se compara com None.
    ordered = sorted(
        trades,
        key=lambda t: (t["traded_on"], t.get("created_at") is None, t.get("created_at") or EPOCH),
    )

    for trade in ordered:
        position = positions.setdefault(
            trade["ticker"],
            Position(trade["ticker"], trade["price_currency"], trade["quote_currency"]),
        )
        quantity, price = trade["quantity"], trade["unit_price"]

        if trade["side"] == "compra":
            total = position.quantity * position.average_price + quantity * price
            position.quantity += quantity
            position.average_price = total / position.quantity
            continue

        if quantity > position.quantity:
            raise PortfolioError(
                f"Em {trade['traded_on']:%d/%m/%Y} a carteira tinha {_number(position.quantity)} "
                f"{trade['ticker']}, menos que os {_number(quantity)} da venda."
            )
        position.realized += quantity * (price - position.average_price)
        position.quantity -= quantity
        if position.quantity == ZERO:
            position.average_price = ZERO

    return positions


def _number(value: Decimal) -> str:
    return format(value.normalize(), "f")


# Operações ─────────────────────────────────────────────────────────────────

TRADE_COLUMNS = (
    "id, ticker, side, quantity, unit_price, price_currency, quote_currency, traded_on, created_at"
)


async def list_trades(
    pool: AsyncConnectionPool, user_id: UUID, ticker: str | None = None
) -> list[Row]:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"""
            SELECT {TRADE_COLUMNS}
            FROM core.portfolio_trades
            WHERE user_id = %s AND (%s::text IS NULL OR ticker = %s)
            ORDER BY ticker, traded_on, created_at
            """,
            (user_id, ticker, ticker),
        )
        return await cursor.fetchall()


async def add_trade(
    pool: AsyncConnectionPool,
    user_id: UUID,
    *,
    ticker: str,
    side: Side,
    quantity: Decimal,
    unit_price: Decimal,
    price_currency: str,
    quote_currency: str,
    traded_on: date,
) -> tuple[Row, Position]:
    """Grava a operação se a sequência continuar válida e devolve a posição nova."""
    async with pool.connection() as conn, conn.transaction():
        # Duas operações simultâneas no mesmo ativo poderiam, juntas, vender mais
        # do que existe; o lock por usuário e ativo as coloca em fila.
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{user_id}:{ticker}",)
        )
        cursor = await conn.execute(
            f"SELECT {TRADE_COLUMNS} FROM core.portfolio_trades WHERE user_id = %s AND ticker = %s",
            (user_id, ticker),
        )
        trades = await cursor.fetchall()

        # Um preço médio só faz sentido numa moeda: misturar compras em reais e em
        # dólar exigiria o câmbio de cada data.
        used = {trade["price_currency"] for trade in trades}
        if used and price_currency not in used:
            raise PortfolioError(
                f"A carteira registra {ticker} com preços em {used.pop()}; registre esta "
                "operação na mesma moeda."
            )

        new = {
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "unit_price": unit_price,
            "price_currency": price_currency,
            "quote_currency": quote_currency,
            "traded_on": traded_on,
        }
        position = replay([*trades, new])[ticker]

        cursor = await conn.execute(
            f"""
            INSERT INTO core.portfolio_trades
                (user_id, ticker, side, quantity, unit_price, price_currency, quote_currency, traded_on)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {TRADE_COLUMNS}
            """,
            (user_id, ticker, side, quantity, unit_price, price_currency, quote_currency, traded_on),
        )
        return await cursor.fetchone(), position


# Watchlist ─────────────────────────────────────────────────────────────────

WATCH_COLUMNS = "id, ticker, operation, target_price, quantity, currency, created_at"


async def list_watch(
    pool: AsyncConnectionPool, user_id: UUID, ticker: str | None = None
) -> list[Row]:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"""
            SELECT {WATCH_COLUMNS}
            FROM core.watchlist
            WHERE user_id = %s AND (%s::text IS NULL OR ticker = %s)
            ORDER BY ticker, operation, target_price
            """,
            (user_id, ticker, ticker),
        )
        return await cursor.fetchall()


async def add_watch(
    pool: AsyncConnectionPool,
    user_id: UUID,
    *,
    ticker: str,
    operation: Operation,
    target_price: Decimal,
    quantity: Decimal | None,
    currency: str,
) -> Row:
    try:
        async with pool.connection() as conn:
            cursor = await conn.execute(
                f"""
                INSERT INTO core.watchlist (user_id, ticker, operation, target_price, quantity, currency)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING {WATCH_COLUMNS}
                """,
                (user_id, ticker, operation, target_price, quantity, currency),
            )
            return await cursor.fetchone()
    except errors.UniqueViolation:
        raise PortfolioError(
            f"A watchlist já tem {operation} de {ticker} a {_number(target_price)}."
        ) from None


async def remove_watch(
    pool: AsyncConnectionPool,
    user_id: UUID,
    *,
    ticker: str,
    operation: Operation,
    target_price: Decimal | None,
) -> Row:
    """Remove a entrada indicada; sem preço alvo, só se ela for a única."""
    async with pool.connection() as conn, conn.transaction():
        cursor = await conn.execute(
            f"""
            SELECT {WATCH_COLUMNS} FROM core.watchlist
            WHERE user_id = %s AND ticker = %s AND operation = %s
              AND (%s::numeric IS NULL OR target_price = %s)
            FOR UPDATE
            """,
            (user_id, ticker, operation, target_price, target_price),
        )
        matches = await cursor.fetchall()

        if not matches:
            raise PortfolioError(f"A watchlist não tem {operation} de {ticker} com esses dados.")
        if len(matches) > 1:
            targets = ", ".join(_number(match["target_price"]) for match in matches)
            raise PortfolioError(
                f"Há {len(matches)} entradas de {operation} de {ticker} (alvos {targets}); "
                "informe o preço alvo da que deve sair."
            )

        await conn.execute("DELETE FROM core.watchlist WHERE id = %s", (matches[0]["id"],))
        return matches[0]
