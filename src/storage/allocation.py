"""Alocação-alvo do usuário e as classes que ele escolheu por ativo, no schema
`core` (docs/adr/0004)."""

from decimal import Decimal
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from src.storage.conversations import Row

# As classes de ativo com alvo, na ordem em que aparecem.
CLASSES = ("acoes_br", "fundos", "etfs", "exterior", "cripto")

COLUMNS = ", ".join((*CLASSES, "tolerance", "updated_at"))


async def get_targets(pool: AsyncConnectionPool, user_id: UUID) -> Row | None:
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"SELECT {COLUMNS} FROM core.allocation_targets WHERE user_id = %s", (user_id,)
        )
        return await cursor.fetchone()


async def set_targets(
    pool: AsyncConnectionPool, user_id: UUID, weights: dict[str, Decimal], tolerance: Decimal
) -> Row:
    """Grava a alocação-alvo, substituindo a anterior."""
    values = [weights[name] for name in CLASSES]
    assignments = ", ".join(f"{name} = EXCLUDED.{name}" for name in (*CLASSES, "tolerance"))
    async with pool.connection() as conn:
        cursor = await conn.execute(
            f"""
            INSERT INTO core.allocation_targets (user_id, {", ".join(CLASSES)}, tolerance)
            VALUES (%s, {", ".join(["%s"] * len(CLASSES))}, %s)
            ON CONFLICT (user_id) DO UPDATE SET {assignments}, updated_at = now()
            RETURNING {COLUMNS}
            """,
            (user_id, *values, tolerance),
        )
        return await cursor.fetchone()


async def list_overrides(pool: AsyncConnectionPool, user_id: UUID) -> dict[str, str]:
    """A classe escolhida pelo usuário para cada ativo que ele corrigiu."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT ticker, asset_class FROM core.asset_class_overrides WHERE user_id = %s", (user_id,)
        )
        return {row["ticker"]: row["asset_class"] for row in await cursor.fetchall()}


async def set_override(pool: AsyncConnectionPool, user_id: UUID, ticker: str, asset_class: str) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO core.asset_class_overrides (user_id, ticker, asset_class)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, ticker) DO UPDATE SET asset_class = EXCLUDED.asset_class, updated_at = now()
            """,
            (user_id, ticker, asset_class),
        )


async def remove_override(pool: AsyncConnectionPool, user_id: UUID, ticker: str) -> bool:
    """Volta o ativo à classe automática; diz se havia uma escolha a remover."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "DELETE FROM core.asset_class_overrides WHERE user_id = %s AND ticker = %s", (user_id, ticker)
        )
        return cursor.rowcount > 0
