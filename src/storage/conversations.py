"""Consultas sobre threads e mensagens (schema `agent`)."""

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


# Threads ───────────────────────────────────────────────────────────────────


async def create_thread(pool: AsyncConnectionPool, user_id: UUID, title: str) -> Row:
    return await _one(
        pool,
        f"INSERT INTO agent.threads (user_id, title) VALUES (%s, %s) RETURNING {THREAD_COLUMNS}",
        (user_id, title),
    )


async def get_thread(pool: AsyncConnectionPool, thread_id: UUID, user_id: UUID) -> Row | None:
    """A thread, se existir, pertencer ao usuário e não tiver sido apagada."""
    return await _one(
        pool,
        f"""
        SELECT {THREAD_COLUMNS} FROM agent.threads
         WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """,
        (thread_id, user_id),
    )


def _contains(text: str) -> str:
    """Padrão de LIKE para "contém o texto", com os curingas escapados."""
    escaped = text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


async def list_threads(
    pool: AsyncConnectionPool, user_id: UUID, limit: int, query: str | None = None
) -> list[Row]:
    """As conversas do usuário, da atividade mais recente à mais antiga.

    A atividade é a última mensagem do caminho ativo; num fork recém-criado,
    cuja `head` é uma mensagem antiga, vale a criação da thread.

    Com `query`, só as conversas cujo título ou alguma mensagem contém o texto,
    sem diferença de caixa nem de acento; `match` traz a mensagem mais recente
    que o contém, se houver.
    """
    return await _all(
        pool,
        """
        SELECT threads.id,
               threads.title,
               threads.forked_from_message_id IS NOT NULL AS is_fork,
               head.state AS head_state,
               GREATEST(threads.created_at, head.created_at) AS updated_at,
               found.content AS match
          FROM agent.threads
          LEFT JOIN agent.messages head ON head.id = threads.head_message_id
          LEFT JOIN LATERAL (
                SELECT message.content
                  FROM agent.messages message
                 WHERE %(pattern)s::text IS NOT NULL
                   AND message.thread_id = threads.id
                   AND message.role IN ('user', 'assistant')
                   AND unaccent(message.content) ILIKE unaccent(%(pattern)s::text)
                 ORDER BY message.created_at DESC
                 LIMIT 1
          ) found ON true
         WHERE threads.user_id = %(user_id)s
           AND threads.deleted_at IS NULL
           AND (%(pattern)s::text IS NULL
                OR unaccent(coalesce(threads.title, '')) ILIKE unaccent(%(pattern)s::text)
                OR found.content IS NOT NULL)
         ORDER BY updated_at DESC, threads.id DESC
         LIMIT %(limit)s
        """,
        {"user_id": user_id, "limit": limit, "pattern": _contains(query) if query else None},
    )


async def rename_thread(pool: AsyncConnectionPool, thread_id: UUID, user_id: UUID, title: str) -> bool:
    row = await _one(
        pool,
        """
        UPDATE agent.threads SET title = %s
         WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        RETURNING id
        """,
        (title, thread_id, user_id),
    )
    return row is not None


async def delete_thread(pool: AsyncConnectionPool, thread_id: UUID, user_id: UUID) -> bool:
    """Esconde a conversa e tira os turnos dela da memória do agente.

    As mensagens ficam: uma bifurcação pode subir até elas. As memórias
    `conversa` dos turnos desta thread são só o índice de busca deles e saem de
    vez; se uma delas tinha substituído a versão de um turno de outra thread (a
    regeneração num fork), a versão anterior volta a valer. Os fatos sobre o
    usuário guardados nesta conversa continuam.
    """
    row = await _one(
        pool,
        """
        WITH thread AS (
            UPDATE agent.threads SET deleted_at = now()
             WHERE id = %(thread_id)s AND user_id = %(user_id)s AND deleted_at IS NULL
            RETURNING id
        ),
        turns AS (
            SELECT DISTINCT sources.memory_id
              FROM agent.memory_sources sources
              JOIN agent.messages message ON message.id = sources.message_id
              JOIN agent.memories memory ON memory.id = sources.memory_id
             WHERE message.thread_id IN (SELECT id FROM thread)
               AND memory.category = 'conversa'
        ),
        revived AS (
            UPDATE agent.memories SET superseded_by_id = NULL
             WHERE superseded_by_id IN (SELECT memory_id FROM turns)
               AND id NOT IN (SELECT memory_id FROM turns)
        ),
        unlinked AS (
            DELETE FROM agent.memory_sources WHERE memory_id IN (SELECT memory_id FROM turns)
        ),
        removed AS (
            DELETE FROM agent.memories WHERE id IN (SELECT memory_id FROM turns)
        )
        SELECT count(*) AS deleted FROM thread
        """,
        {"thread_id": thread_id, "user_id": user_id},
    )
    return row["deleted"] > 0


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
