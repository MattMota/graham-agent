"""Streams retomáveis: o turno roda desacoplado da conexão HTTP.

Cada turno grava os seus eventos SSE num Redis Stream, e a conexão do navegador
só lê dele. Se ela cair (a página recarregou, a rede piscou), o turno continua
rodando no servidor; uma conexão nova lê o stream do começo, para redesenhar a
resposta, ou a partir do último evento que recebeu.

Chaves no Redis, todas com TTL de 1h:

    graham:stream:{id}          os eventos do turno, em ordem
    graham:stream:{id}:meta     a conversa e o usuário donos do stream
    graham:thread:{id}:active   o stream em andamento na conversa, se houver
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable
from typing import Any
from uuid import UUID, uuid4

import anyio
import redis.asyncio as aioredis

from src.storage.cache import key

logger = logging.getLogger("uvicorn.error")

STREAM_TTL = 60 * 60

# Quanto a leitura espera por eventos novos antes de mandar um sinal de vida.
# Fica abaixo do `cache.SOCKET_TIMEOUT`, ou o cliente desistiria no meio da espera.
READ_BLOCK_MS = 5_000


class ThreadBusy(Exception):
    """A conversa já tem um turno em andamento."""


def _stream(stream_id: str) -> str:
    return key("stream", stream_id)


def _meta(stream_id: str) -> str:
    return key("stream", stream_id, "meta")


def _active(thread_id: UUID) -> str:
    return key("thread", thread_id, "active")


def frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# O turno acabou sem chegar ao fim (o servidor parou). A interface relê a
# conversa do Postgres, onde a mensagem ficou como interrompida.
INTERRUPTED = frame("done", {"message_id": None, "state": "interrupted"})


# Reserva ────────────────────────────────────────────────────────────────────


async def reserve(redis: aioredis.Redis, thread_id: UUID, user_id: UUID) -> str:
    """Reserva a conversa para um turno novo e devolve o id do stream.

    Um turno por vez: com outro em andamento, duas respostas escreveriam no
    mesmo caminho ao mesmo tempo.
    """
    stream_id = str(uuid4())
    meta = {"id": stream_id, "thread_id": str(thread_id), "user_id": str(user_id)}
    if not await redis.set(_active(thread_id), json.dumps(meta), nx=True, ex=STREAM_TTL):
        raise ThreadBusy
    await redis.set(_meta(stream_id), json.dumps(meta), ex=STREAM_TTL)
    # O primeiro evento já cria o stream: quem chegar para ler encontra algo.
    await redis.xadd(_stream(stream_id), {"event": "stream", "frame": frame("stream", {"id": stream_id})})
    await redis.expire(_stream(stream_id), STREAM_TTL)
    return stream_id


async def describe(redis: aioredis.Redis, thread_id: UUID, stream_id: str, after_message_id: UUID) -> None:
    """Registra a partir de qual mensagem o turno escreve.

    Quem abrir a conversa no meio do turno vê o histórico só até ela e redesenha
    o resto pelo stream, sem mostrar duas vezes o que já foi gravado.
    """
    raw = await redis.get(_active(thread_id))
    if raw is None:
        return
    meta = json.loads(raw)
    if meta["id"] == stream_id:
        meta["after_message_id"] = str(after_message_id)
        await redis.set(_active(thread_id), json.dumps(meta), ex=STREAM_TTL)


async def active(redis: aioredis.Redis, thread_id: UUID) -> dict[str, Any] | None:
    raw = await redis.get(_active(thread_id))
    meta = None if raw is None else json.loads(raw)
    return meta if meta and meta.get("after_message_id") else None


async def owner(redis: aioredis.Redis, stream_id: str) -> dict[str, Any] | None:
    raw = await redis.get(_meta(stream_id))
    return None if raw is None else json.loads(raw)


async def release(redis: aioredis.Redis, thread_id: UUID, stream_id: str) -> None:
    """Libera a conversa, se ela ainda estiver reservada para este stream."""
    raw = await redis.get(_active(thread_id))
    if raw is not None and json.loads(raw)["id"] == stream_id:
        await redis.delete(_active(thread_id))


# Produção ───────────────────────────────────────────────────────────────────


async def produce(
    redis: aioredis.Redis, thread_id: UUID, stream_id: str, frames: AsyncIterator[str]
) -> None:
    """Grava no stream cada evento do turno, até o `done`."""
    key_ = _stream(stream_id)
    finished = False
    try:
        async for item in frames:
            event = item.split("\n", 1)[0].removeprefix("event: ")
            if event == "done":
                # A conversa é liberada antes de o fim ser anunciado: quem lê o
                # `done` e manda a próxima pergunta na hora não pode encontrá-la
                # ainda reservada. Nada do turno é gravado depois do `done`.
                await release(redis, thread_id, stream_id)
                finished = True
            await redis.xadd(key_, {"event": event, "frame": item})
            await redis.expire(key_, STREAM_TTL)
    finally:
        # Cancelado (o servidor está parando) ou não, o stream precisa terminar
        # e a conversa precisa ser liberada; o escudo deixa estas escritas
        # acontecerem mesmo durante o cancelamento.
        with anyio.CancelScope(shield=True):
            await frames.aclose()
            try:
                if not finished:
                    await release(redis, thread_id, stream_id)
                    await redis.xadd(key_, {"event": "done", "frame": INTERRUPTED})
            except Exception:  # noqa: BLE001 - o Redis caiu junto; a subida seguinte limpa
                logger.exception("Não foi possível fechar o stream %s", stream_id)


def spawn(tasks: set[asyncio.Task], work: Awaitable[None]) -> asyncio.Task:
    """Roda o turno em segundo plano, guardando a referência até ele acabar."""
    task = asyncio.create_task(work)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return task


# Leitura ────────────────────────────────────────────────────────────────────


async def consume(redis: aioredis.Redis, stream_id: str, after: str = "0") -> AsyncIterator[str]:
    """Os eventos do stream depois de `after`, até o `done`.

    Cada evento sai com o id do Redis no campo `id:` do SSE, que a interface
    guarda para retomar exatamente dali se a conexão cair.
    """
    key_ = _stream(stream_id)
    last = after
    while True:
        entries = await redis.xread({key_: last}, block=READ_BLOCK_MS, count=200)
        if not entries:
            # Sem stream e sem dono: expirou, ou o Redis foi reiniciado.
            if not await redis.exists(key_) and await owner(redis, stream_id) is None:
                return
            # Comentário SSE: mantém a conexão viva e não vira evento na interface.
            yield ": ping\n\n"
            continue
        for entry_id, fields in entries[0][1]:
            last = entry_id
            yield f"id: {entry_id}\n{fields['frame']}"
            if fields["event"] == "done":
                return


# Subida ─────────────────────────────────────────────────────────────────────


async def recover(redis: aioredis.Redis) -> int:
    """Encerra os streams que o processo anterior deixou abertos ao parar."""
    count = 0
    async for entry in redis.scan_iter(match=key("thread", "*", "active"), count=500):
        raw = await redis.get(entry)
        if raw is not None:
            stream_id = json.loads(raw)["id"]
            await redis.xadd(_stream(stream_id), {"event": "done", "frame": INTERRUPTED})
            await redis.expire(_stream(stream_id), STREAM_TTL)
            count += 1
        await redis.delete(entry)
    return count

