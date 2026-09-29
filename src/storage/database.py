"""Pool de conexões com o Postgres, compartilhado pelo servidor e pelo checkpointer."""

import os

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


async def _configure(conn: AsyncConnection) -> None:
    # O checkpointer do LangGraph usa nomes de tabela sem schema; este
    # search_path os leva para `langgraph`. As nossas consultas sempre
    # qualificam o schema, então não dependem dele.
    await conn.execute("SET search_path TO langgraph, public")


def create_pool() -> AsyncConnectionPool:
    """Cria o pool, fechado; `async with` o abre e o fecha."""
    return AsyncConnectionPool(
        os.environ["DATABASE_URL"],
        open=False,
        configure=_configure,
        # Exigências do AsyncPostgresSaver, que funcionam também para nós.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
