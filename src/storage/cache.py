"""Redis: o cliente do servidor e o cache dos dados de mercado.

O cache falha aberto: se o Redis não responder, a consulta vai direto à Yahoo
e a escrita é ignorada. O cache acelera; nunca é a única cópia de nada.

As conversas ficam fora de propósito: lê-las do Postgres custa cerca de 1 ms,
nada perto dos segundos de um turno, e uma cópia no Redis só traria memória
ocupada e o risco de mostrar uma versão desatualizada.
"""

import functools
import hashlib
import json
import logging
import os
from typing import Any, Callable

import redis
import redis.asyncio as aioredis

logger = logging.getLogger("uvicorn.error")

PREFIX = "graham"

# Tempo máximo de espera por uma resposta do Redis, em segundos.
SOCKET_TIMEOUT = 10


def key(*parts: Any) -> str:
    return ":".join([PREFIX, *(str(part) for part in parts)])


# Cliente do servidor ────────────────────────────────────────────────────────

# Aberto na subida do servidor, para os streams retomáveis.
client: aioredis.Redis | None = None


async def connect() -> aioredis.Redis:
    global client
    client = aioredis.Redis.from_url(
        os.environ["REDIS_URL"],
        decode_responses=True,
        # Precisa ser maior que o bloqueio da leitura dos streams
        # (`streams.READ_BLOCK_MS`): o socket não pode desistir antes dele.
        socket_timeout=SOCKET_TIMEOUT,
    )
    await client.ping()
    return client


async def close() -> None:
    global client
    if client is not None:
        await client.aclose()
        client = None


# Dados de mercado ───────────────────────────────────────────────────────────

_sync_client: redis.Redis | None = None


def _sync() -> redis.Redis | None:
    """Cliente síncrono das ferramentas, que rodam em threads fora do event loop."""
    global _sync_client
    if _sync_client is None and os.getenv("REDIS_URL"):
        _sync_client = redis.Redis.from_url(
            os.environ["REDIS_URL"], decode_responses=True, socket_timeout=1
        )
    return _sync_client


def cached(
    name: str, ttl: int, keep: Callable[[dict], bool] = lambda result: True
) -> Callable[[Callable[..., dict]], Callable[..., dict]]:
    """Guarda o retorno da função por `ttl` segundos, pela combinação de argumentos.

    Só o que deu certo entra no cache: uma exceção sobe sem ser guardada, e um
    resultado que `keep` recusa também não. Um resultado vazio, por exemplo,
    pode ser uma falha da fonte, e guardá-lo prolongaria a falha por todo o TTL.
    """

    def decorator(function: Callable[..., dict]) -> Callable[..., dict]:
        @functools.wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> dict:
            arguments = json.dumps([args, kwargs], sort_keys=True, default=str)
            entry = key("market", name, hashlib.sha1(arguments.encode()).hexdigest())
            store = _sync()

            if store is not None:
                try:
                    hit = store.get(entry)
                    if hit is not None:
                        return json.loads(hit)
                except redis.RedisError:
                    logger.warning("Cache de mercado indisponível; consultando a Yahoo direto")
                    store = None

            result = function(*args, **kwargs)
            if store is not None and keep(result):
                try:
                    store.set(entry, json.dumps(result, default=str), ex=ttl)
                except redis.RedisError:
                    pass
            return result

        return wrapper

    return decorator
