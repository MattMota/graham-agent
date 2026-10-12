"""Tokens de acesso ao servidor MCP (schema `core`)."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

Row = dict[str, Any]
Kind = Literal["chave", "interno"]

# Prefixo que deixa a chave reconhecível num arquivo de configuração ou num
# vazamento (e por scanners de segredos).
PREFIX = "graham_"

# Quanto o "último uso" pode atrasar: gravá-lo a cada chamada seria uma escrita
# por ferramenta.
LAST_USED_GRANULARITY = timedelta(minutes=1)

KEY_COLUMNS = "id, name, scopes, created_at, last_used_at"


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


async def _one(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> Row | None:
    async with pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return await cursor.fetchone()


async def _all(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> list[Row]:
    async with pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return await cursor.fetchall()


async def _execute(pool: AsyncConnectionPool, query: str, params: tuple = ()) -> int:
    async with pool.connection() as conn:
        cursor = await conn.execute(query, params)
        return cursor.rowcount


async def issue(
    pool: AsyncConnectionPool,
    user_id: UUID,
    kind: Kind,
    scopes: list[str],
    *,
    name: str | None = None,
    ttl: timedelta | None = None,
) -> tuple[str, Row]:
    """Cria um token e devolve o valor, que não é guardado e só existe agora."""
    token = PREFIX + secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + ttl if ttl else None
    row = await _one(
        pool,
        f"""
        INSERT INTO core.access_tokens (user_id, token_hash, kind, name, scopes, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING {KEY_COLUMNS}
        """,
        (user_id, token_hash(token), kind, name, scopes, expires_at),
    )
    return token, row


async def verify(pool: AsyncConnectionPool, token: str) -> Row | None:
    """O token, se existir, não tiver vencido nem sido revogado."""
    row = await _one(
        pool,
        """
        SELECT id, user_id, kind, scopes, expires_at, last_used_at
          FROM core.access_tokens
         WHERE token_hash = %s
           AND revoked_at IS NULL
           AND (expires_at IS NULL OR expires_at > now())
        """,
        (token_hash(token),),
    )
    if row and row["kind"] == "chave":
        stale = row["last_used_at"] is None or (
            datetime.now(timezone.utc) - row["last_used_at"] > LAST_USED_GRANULARITY
        )
        if stale:
            await _execute(pool, "UPDATE core.access_tokens SET last_used_at = now() WHERE id = %s", (row["id"],))
    return row


async def discard(pool: AsyncConnectionPool, token: str) -> None:
    """Apaga um token interno ao fim do turno."""
    await _execute(
        pool, "DELETE FROM core.access_tokens WHERE token_hash = %s AND kind = 'interno'", (token_hash(token),)
    )


async def list_keys(pool: AsyncConnectionPool, user_id: UUID) -> list[Row]:
    return await _all(
        pool,
        f"""
        SELECT {KEY_COLUMNS} FROM core.access_tokens
         WHERE user_id = %s AND kind = 'chave' AND revoked_at IS NULL
         ORDER BY created_at DESC
        """,
        (user_id,),
    )


async def revoke_key(pool: AsyncConnectionPool, user_id: UUID, key_id: UUID) -> bool:
    revoked = await _execute(
        pool,
        """
        UPDATE core.access_tokens SET revoked_at = now()
         WHERE id = %s AND user_id = %s AND kind = 'chave' AND revoked_at IS NULL
        """,
        (key_id, user_id),
    )
    return revoked > 0


async def purge(pool: AsyncConnectionPool) -> int:
    """Apaga os tokens internos vencidos (um turno que caiu antes de apagar o seu)."""
    return await _execute(
        pool, "DELETE FROM core.access_tokens WHERE kind = 'interno' AND expires_at <= now()"
    )
