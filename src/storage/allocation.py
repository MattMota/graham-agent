"""Alocação-alvo do usuário, no schema `core` (docs/adr/0004)."""

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
