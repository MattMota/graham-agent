"""Streams retomáveis: a execução roda desacoplada da conexão HTTP.

Cada execução do agente grava os seus eventos AG-UI num Redis Stream, e a
conexão do cliente só lê dele. Se ela cair (a página recarregou, a rede
piscou), a execução continua no servidor; uma conexão nova lê o stream do
começo, para redesenhar a resposta, ou a partir do último evento que recebeu.
O AG-UI não define essa retomada: ela é do Graham, com o `id:` do SSE.

O id do stream é o `runId` da execução. Chaves no Redis, todas com TTL de 1h:

    graham:stream:{id}          os eventos da execução, em ordem
    graham:stream:{id}:meta     a conversa e o usuário donos do stream
    graham:thread:{id}:active   o stream em andamento na conversa, se houver
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable
from typing import Any
from uuid import UUID

import anyio
import redis.asyncio as aioredis
from ag_ui.core import BaseEvent, EventType, RunErrorEvent

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


# Os eventos que encerram uma execução: depois deles, nada mais é gravado.
TERMINAL = {EventType.RUN_FINISHED.value, EventType.RUN_ERROR.value}


def frame(data: str, entry_id: str | None = None) -> str:
    """Um evento no formato SSE, com o id do Redis quando ele veio do stream."""
    return (f"id: {entry_id}\n" if entry_id else "") + f"data: {data}\n\n"


def encode(event: BaseEvent) -> str:
    """O evento em JSON, como o AG-UI o define (camelCase, sem campos vazios)."""
    return event.model_dump_json(by_alias=True)


# A execução acabou sem chegar ao fim (o servidor parou). O cliente relê a
# conversa, onde a mensagem ficou como interrompida.
INTERRUPTED = encode(RunErrorEvent(
    message="O servidor parou antes do fim da resposta.", code="interrupted"
))


# Reserva ────────────────────────────────────────────────────────────────────


class RunExists(Exception):
    """Já houve uma execução com este `runId`."""


async def reserve(redis: aioredis.Redis, thread_id: UUID, user_id: UUID, run_id: UUID) -> str:
    """Reserva a conversa para uma execução nova e devolve o id do stream.

    Uma execução por vez: com outra em andamento, duas respostas escreveriam no
    mesmo caminho ao mesmo tempo. O id é o `runId` que o cliente gerou; um que
    já foi usado é recusado, para ninguém ler o stream de outra execução.
    """
    stream_id = str(run_id)
    meta = {"id": stream_id, "thread_id": str(thread_id), "user_id": str(user_id)}
    if not await redis.set(_meta(stream_id), json.dumps(meta), nx=True, ex=STREAM_TTL):
        raise RunExists
    if not await redis.set(_active(thread_id), json.dumps(meta), nx=True, ex=STREAM_TTL):
        await redis.delete(_meta(stream_id))
        raise ThreadBusy
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


async def busy(redis: aioredis.Redis, thread_ids: list[UUID]) -> set[UUID]:
    """As conversas, entre estas, com um turno em andamento."""
    if not thread_ids:
        return set()
    reserved = await redis.mget([_active(thread_id) for thread_id in thread_ids])
    return {thread_id for thread_id, raw in zip(thread_ids, reserved) if raw is not None}


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
    redis: aioredis.Redis, thread_id: UUID, stream_id: str, events: AsyncIterator[BaseEvent]
) -> None:
    """Grava no stream cada evento da execução, até o que a encerra."""
    key_ = _stream(stream_id)
    finished = False
    try:
        async for event in events:
            if event.type.value in TERMINAL:
                # A conversa é liberada antes de o fim ser anunciado: quem lê o
                # fim e manda a próxima pergunta na hora não pode encontrá-la
                # ainda reservada. Nada da execução é gravado depois dele.
                await release(redis, thread_id, stream_id)
                finished = True
            await redis.xadd(key_, {"type": event.type.value, "data": encode(event)})
            await redis.expire(key_, STREAM_TTL)
    finally:
        # Cancelado (o servidor está parando) ou não, o stream precisa terminar
        # e a conversa precisa ser liberada; o escudo deixa estas escritas
        # acontecerem mesmo durante o cancelamento.
        with anyio.CancelScope(shield=True):
            await events.aclose()
            try:
                if not finished:
                    await release(redis, thread_id, stream_id)
                    await _close(redis, stream_id)
            except Exception:  # noqa: BLE001 - o Redis caiu junto; a subida seguinte limpa
                logger.exception("Não foi possível fechar o stream %s", stream_id)


async def _close(redis: aioredis.Redis, stream_id: str) -> None:
    """Encerra o stream de uma execução que parou no meio."""
    await redis.xadd(_stream(stream_id), {"type": EventType.RUN_ERROR.value, "data": INTERRUPTED})
    await redis.expire(_stream(stream_id), STREAM_TTL)


def spawn(tasks: set[asyncio.Task], work: Awaitable[None]) -> asyncio.Task:
    """Roda o turno em segundo plano, guardando a referência até ele acabar."""
    task = asyncio.create_task(work)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return task


# Leitura ────────────────────────────────────────────────────────────────────


async def consume(redis: aioredis.Redis, stream_id: str, after: str = "0") -> AsyncIterator[str]:
    """Os eventos do stream depois de `after`, até o que encerra a execução.

    Cada evento sai com o id do Redis no campo `id:` do SSE, que o cliente
    guarda para retomar exatamente dali se a conexão cair (pelo `?after=` ou
    pelo cabeçalho `Last-Event-ID`, que o `EventSource` manda sozinho).
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
            yield frame(fields["data"], entry_id)
            if fields["type"] in TERMINAL:
                return


# Subida ─────────────────────────────────────────────────────────────────────


async def recover(redis: aioredis.Redis) -> int:
    """Encerra os streams que o processo anterior deixou abertos ao parar."""
    count = 0
    async for entry in redis.scan_iter(match=key("thread", "*", "active"), count=500):
        raw = await redis.get(entry)
        if raw is not None:
            await _close(redis, json.loads(raw)["id"])
            count += 1
        await redis.delete(entry)
    return count

