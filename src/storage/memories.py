"""Memórias de longo prazo do usuário (`agent.memories` e `agent.memory_sources`)."""

from typing import Literal
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from src.storage.conversations import Row

Category = Literal["perfil", "preferencia", "interesse", "episodio", "conversa"]

MEMORY_COLUMNS = "id, category, content, created_at"

# Ainda vale: nem esquecida, nem substituída por uma versão mais nova.
ACTIVE = "NOT is_forgotten AND superseded_by_id IS NULL"


async def _one(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> Row | None:
    async with pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return await cursor.fetchone()


async def _all(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> list[Row]:
    async with pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return await cursor.fetchall()


# Escrita ───────────────────────────────────────────────────────────────────


async def add_memory(
    pool: AsyncConnectionPool,
    user_id: UUID,
    category: Category,
    content: str,
    *,
    embedding: str | None = None,
    embedding_model: str | None = None,
) -> Row:
    return await _one(
        pool,
        f"""
        INSERT INTO agent.memories (user_id, category, content, embedding, embedding_model)
        VALUES (%s, %s, %s, %s::halfvec, %s)
        RETURNING {MEMORY_COLUMNS}
        """,
        (user_id, category, content, embedding, embedding_model),
    )


async def set_embedding(
    pool: AsyncConnectionPool, memory_id: UUID, embedding: str, embedding_model: str
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE agent.memories SET embedding = %s::halfvec, embedding_model = %s WHERE id = %s",
            (embedding, embedding_model, memory_id),
        )


async def add_sources(pool: AsyncConnectionPool, memory_id: UUID, message_ids: list[UUID]) -> None:
    async with pool.connection() as conn:
        for message_id in message_ids:
            await conn.execute(
                "INSERT INTO agent.memory_sources (memory_id, message_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (memory_id, message_id),
            )


async def supersede(pool: AsyncConnectionPool, old_id: UUID, new_id: UUID) -> None:
    """A memória antiga passa a apontar para a versão que a substituiu."""
    async with pool.connection() as conn:
        await conn.execute(
            f"UPDATE agent.memories SET superseded_by_id = %s WHERE id = %s AND {ACTIVE}",
            (new_id, old_id),
        )


async def forget(pool: AsyncConnectionPool, user_id: UUID, memory_id: UUID) -> Row | None:
    """Marca como esquecida. Nunca apaga: é o sinal de erro para o fine-tuning."""
    return await _one(
        pool,
        f"""
        UPDATE agent.memories SET is_forgotten = true, forgotten_at = now()
        WHERE id = %s AND user_id = %s AND NOT is_forgotten
        RETURNING {MEMORY_COLUMNS}
        """,
        (memory_id, user_id),
    )


async def set_forgotten_by(pool: AsyncConnectionPool, memory_id: UUID, message_id: UUID) -> None:
    """Registra qual mensagem do agente pediu o esquecimento."""
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE agent.memories SET forgotten_by_message_id = %s WHERE id = %s AND is_forgotten",
            (message_id, memory_id),
        )


# Leitura ───────────────────────────────────────────────────────────────────


async def search(
    pool: AsyncConnectionPool, user_id: UUID, query: str, embedding: str | None, limit: int
) -> list[Row]:
    """Busca híbrida (semântica e lexical, combinadas por RRF) no banco."""
    return await _all(
        pool,
        "SELECT * FROM agent.search_memories(%s, %s, %s::halfvec, %s)",
        (user_id, query, embedding, limit),
    )


async def get_memory(pool: AsyncConnectionPool, user_id: UUID, memory_id: UUID) -> Row | None:
    return await _one(
        pool,
        f"""
        SELECT {MEMORY_COLUMNS}, is_forgotten, superseded_by_id,
               array(SELECT message_id FROM agent.memory_sources WHERE memory_id = memory.id) AS sources
        FROM agent.memories AS memory
        WHERE id = %s AND user_id = %s
        """,
        (memory_id, user_id),
    )


async def similar(
    pool: AsyncConnectionPool, user_id: UUID, embedding: str, exclude_id: UUID, limit: int
) -> list[Row]:
    """As memórias de fato ativas mais parecidas com o embedding, de qualquer categoria.

    `conversa` fica de fora: um turno não é substituído por um fato. As outras
    categorias entram juntas porque o agente pode classificar o mesmo fato de
    jeitos diferentes ("prefere renda fixa" como perfil ou como preferência).
    """
    return await _all(
        pool,
        f"""
        SELECT {MEMORY_COLUMNS}, 1 - (embedding <=> %s::halfvec) AS similarity
        FROM agent.memories
        WHERE user_id = %s AND category <> 'conversa' AND id <> %s
          AND embedding IS NOT NULL AND {ACTIVE}
        ORDER BY embedding <=> %s::halfvec
        LIMIT %s
        """,
        (embedding, user_id, exclude_id, embedding, limit),
    )


async def profile(pool: AsyncConnectionPool, user_id: UUID, limit: int) -> list[Row]:
    """Perfil e preferências ativos, os mais recentes primeiro."""
    return await _all(
        pool,
        f"""
        SELECT {MEMORY_COLUMNS} FROM agent.memories
        WHERE user_id = %s AND category IN ('perfil', 'preferencia') AND {ACTIVE}
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (user_id, limit),
    )


async def pending_embeddings(pool: AsyncConnectionPool, limit: int = 200) -> list[Row]:
    """Memórias ativas que ficaram sem embedding (o servidor caiu, o provedor falhou)."""
    return await _all(
        pool,
        f"SELECT id, content FROM agent.memories WHERE embedding IS NULL AND {ACTIVE} ORDER BY created_at LIMIT %s",
        (limit,),
    )


async def turn_versions(
    pool: AsyncConnectionPool, user_id: UUID, question_id: UUID, exclude_id: UUID
) -> list[Row]:
    """Memórias `conversa` ativas de outras respostas à mesma pergunta (regenerações)."""
    return await _all(
        pool,
        """
        SELECT memory.id FROM agent.memories AS memory
        JOIN agent.memory_sources AS source ON source.memory_id = memory.id
        WHERE memory.user_id = %s AND memory.category = 'conversa' AND source.message_id = %s
          AND memory.id <> %s AND NOT memory.is_forgotten AND memory.superseded_by_id IS NULL
        """,
        (user_id, question_id, exclude_id),
    )
