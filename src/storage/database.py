"""Pool de conexões com o Postgres, compartilhado pelo servidor e pelo checkpointer."""

import os
from pathlib import Path

from psycopg import AsyncConnection, errors
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


async def _configure(conn: AsyncConnection) -> None:
    # O checkpointer do LangGraph usa nomes de tabela sem schema; este
    # search_path os leva para `langgraph`. As nossas consultas sempre
    # qualificam o schema, então não dependem dele.
    await conn.execute("SET search_path TO langgraph, public")


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


async def pending_migrations(pool: AsyncConnectionPool) -> list[str]:
    """As migrations de `db/migrations/` que o banco ainda não aplicou."""
    try:
        async with pool.connection() as conn:
            cursor = await conn.execute("SELECT name FROM public.schema_migrations")
            applied = {row["name"] for row in await cursor.fetchall()}
    except errors.UndefinedTable:
        applied = set()
    return [path.name for path in sorted(MIGRATIONS_DIR.glob("*.sql")) if path.name not in applied]


def create_pool() -> AsyncConnectionPool:
    """Cria o pool, fechado; `async with` o abre e o fecha."""
    return AsyncConnectionPool(
        os.environ["DATABASE_URL"],
        open=False,
        configure=_configure,
        # Exigências do AsyncPostgresSaver, que funcionam também para nós.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
