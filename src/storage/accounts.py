"""Contas e sessões (schema `core`)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import errors
from psycopg_pool import AsyncConnectionPool

Row = dict[str, Any]


async def _one(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> Row | None:
    async with pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return await cursor.fetchone()


async def _execute(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> int:
    async with pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return cursor.rowcount


# Contas ────────────────────────────────────────────────────────────────────


async def create_account(pool: AsyncConnectionPool, email: str, password_hash: str) -> UUID | None:
    """O id da conta nova, ou `None` se o e-mail já estiver cadastrado."""
    try:
        row = await _one(
            pool,
            "INSERT INTO core.users (email, password_hash) VALUES (%s, %s) RETURNING id",
            (email, password_hash),
        )
    except errors.UniqueViolation:
        return None
    return row["id"]


async def find_by_email(pool: AsyncConnectionPool, email: str) -> Row | None:
    return await _one(pool, "SELECT id, email, password_hash FROM core.users WHERE email = %s", (email,))


# Sessões ───────────────────────────────────────────────────────────────────


async def create_session(
    pool: AsyncConnectionPool, user_id: UUID, token_hash: bytes, expires_at: datetime
) -> None:
    await _execute(
        pool,
        "INSERT INTO core.sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
        (token_hash, user_id, expires_at),
    )


async def session_user(pool: AsyncConnectionPool, token_hash: bytes) -> Row | None:
    """O dono da sessão, se ela existir e não tiver vencido."""
    return await _one(
        pool,
        """
        SELECT users.id, users.email
          FROM core.sessions
          JOIN core.users ON users.id = sessions.user_id
         WHERE sessions.token_hash = %s AND sessions.expires_at > now()
        """,
        (token_hash,),
    )


async def delete_session(pool: AsyncConnectionPool, token_hash: bytes) -> None:
    await _execute(pool, "DELETE FROM core.sessions WHERE token_hash = %s", (token_hash,))


async def purge_sessions(pool: AsyncConnectionPool) -> int:
    return await _execute(pool, "DELETE FROM core.sessions WHERE expires_at <= now()")
