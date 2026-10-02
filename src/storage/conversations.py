"""Consultas sobre usuários, threads e mensagens (schemas `core` e `agent`)."""

from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

Row = dict[str, Any]
Role = Literal["user", "assistant", "tool"]
State = Literal["streaming", "awaiting_approval", "completed", "interrupted", "failed"]

THREAD_COLUMNS = "id, user_id, title, forked_from_message_id, head_message_id, created_at"


async def _one(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> Row | None:
    async with pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return await cursor.fetchone()


async def _all(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> list[Row]:
    async with pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return await cursor.fetchall()


def _json(value: Any) -> Jsonb | None:
    return None if value is None else Jsonb(value)


# Usuários ──────────────────────────────────────────────────────────────────


async def create_user(pool: AsyncConnectionPool) -> UUID:
    row = await _one(pool, "INSERT INTO core.users DEFAULT VALUES RETURNING id")
    return row["id"]


async def user_exists(pool: AsyncConnectionPool, user_id: UUID) -> bool:
    return await _one(pool, "SELECT 1 FROM core.users WHERE id = %s", (user_id,)) is not None


# Threads ───────────────────────────────────────────────────────────────────


async def create_thread(pool: AsyncConnectionPool, user_id: UUID, title: str) -> Row:
    return await _one(
        pool,
        f"INSERT INTO agent.threads (user_id, title) VALUES (%s, %s) RETURNING {THREAD_COLUMNS}",
        (user_id, title),
    )


async def get_thread(pool: AsyncConnectionPool, thread_id: UUID, user_id: UUID) -> Row | None:
    """A thread, se existir e pertencer ao usuário."""
    return await _one(
        pool,
        f"SELECT {THREAD_COLUMNS} FROM agent.threads WHERE id = %s AND user_id = %s",
        (thread_id, user_id),
    )


async def fork_thread(
    pool: AsyncConnectionPool, user_id: UUID, title: str | None, message_id: UUID
) -> UUID:
    """Cria uma thread que continua a partir da mensagem, sem copiar o histórico."""
    row = await _one(
        pool,
        """
        INSERT INTO agent.threads (user_id, title, forked_from_message_id, head_message_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (user_id, title, message_id, message_id),
    )
    return row["id"]


async def thread_path(pool: AsyncConnectionPool, thread_id: UUID) -> list[Row]:
    return await _all(pool, "SELECT * FROM agent.thread_path(%s)", (thread_id,))


async def message_path(pool: AsyncConnectionPool, message_id: UUID) -> list[Row]:
    return await _all(pool, "SELECT * FROM agent.message_path(%s)", (message_id,))


# Mensagens ─────────────────────────────────────────────────────────────────


async def add_message(
    pool: AsyncConnectionPool,
    thread_id: UUID,
    parent_id: UUID | None,
    role: Role,
    state: State,
    *,
    content: str = "",
    payload: dict[str, Any] | None = None,
    model: str | None = None,
    params: dict[str, Any] | None = None,
) -> UUID:
    """Insere a mensagem e a torna a `head` da thread."""
    async with pool.connection() as conn, conn.transaction():
        cursor = await conn.execute(
            """
            INSERT INTO agent.messages (thread_id, parent_id, role, state, content, payload, model, params)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (thread_id, parent_id, role, state, content, _json(payload), model, _json(params)),
        )
        message_id = (await cursor.fetchone())["id"]
        await conn.execute(
            "UPDATE agent.threads SET head_message_id = %s WHERE id = %s",
            (message_id, thread_id),
        )
    return message_id


async def get_message(pool: AsyncConnectionPool, message_id: UUID) -> Row | None:
    return await _one(pool, "SELECT * FROM agent.messages WHERE id = %s", (message_id,))


async def update_message(
    pool: AsyncConnectionPool,
    message_id: UUID,
    *,
    content: str,
    state: State,
    payload: dict[str, Any] | None = None,
) -> None:
    """Fecha uma mensagem em geração com o conteúdo final e o estado."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE agent.messages
            SET content = %s, state = %s, payload = coalesce(%s, payload)
            WHERE id = %s
            """,
            (content, state, _json(payload), message_id),
        )


async def revise_message(
    pool: AsyncConnectionPool,
    message_id: UUID,
    *,
    state: State | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Muda o estado ou o payload de uma mensagem já fechada, sem tocar no conteúdo."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE agent.messages
            SET state = coalesce(%s, state), payload = coalesce(%s, payload)
            WHERE id = %s
            """,
            (state, _json(payload), message_id),
        )


async def interrupt_streaming(pool: AsyncConnectionPool) -> int:
    """Marca como interrompido o que estava em geração quando o servidor caiu."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "UPDATE agent.messages SET state = 'interrupted' WHERE state = 'streaming'"
        )
        return cursor.rowcount


# Checkpoints ───────────────────────────────────────────────────────────────


async def expired_graph_threads(pool: AsyncConnectionPool, retention: timedelta) -> list[str]:
    """Threads do LangGraph cujos turnos começaram há mais tempo que a retenção.

    Cada turno roda numa thread do LangGraph nomeada pela primeira mensagem do
    assistente, então a idade do turno é a idade dessa mensagem.
    """
    rows = await _all(
        pool,
        """
        SELECT DISTINCT checkpoint.thread_id
        FROM langgraph.checkpoints AS checkpoint
        JOIN agent.messages AS message ON message.id::text = checkpoint.thread_id
        WHERE message.created_at < now() - %s
        """,
        (retention,),
    )
    return [row["thread_id"] for row in rows]
