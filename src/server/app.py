"""Servidor HTTP do Graham: serve a interface, as conversas e o agente.

O agente fala AG-UI (`src/server/agent.py`); as conversas, as chaves e a conta
são REST, aqui e nos routers incluídos.
"""

import asyncio
import logging
import re
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field, field_validator

from src.agent.memory import processing as memory_processing
from src.agent.runtime.state_graph import compile_graph
from src.agent.tools.registry import load_agent
from src.mcp_server import server as mcp_server
from src.server import agent, auth, keys, streams
from src.server.agui import CHECKPOINT_RETENTION
from src.server.auth import require_user
from src.storage import accounts, cache, conversations, tokens
from src.storage.conversations import MAX_TITLE
from src.storage.database import create_pool, pending_migrations

STATIC_DIR = Path(__file__).parent / "static"

# De quanto em quanto tempo os checkpoints vencidos são apagados.
PURGE_INTERVAL = timedelta(hours=1)

# Quantas conversas a aba lateral lista.
MAX_THREADS = 100

# Quanto texto aparece em volta do trecho encontrado numa busca de conversas.
SNIPPET_RADIUS = 50

logger = logging.getLogger("uvicorn.error")


async def _purge_expired(pool, saver: AsyncPostgresSaver) -> None:
    """Apaga, de hora em hora, os checkpoints que passaram da retenção e as sessões e tokens vencidos."""
    while True:
        try:
            for graph_thread_id in await conversations.expired_graph_threads(pool, CHECKPOINT_RETENTION):
                await saver.adelete_thread(graph_thread_id)
            await accounts.purge_sessions(pool)
            await tokens.purge(pool)
        except Exception:  # noqa: BLE001 - uma falha na limpeza não pode derrubar o servidor
            logger.exception("Falha ao apagar checkpoints, sessões ou tokens vencidos")
        await asyncio.sleep(PURGE_INTERVAL.total_seconds())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # O psycopg assíncrono não funciona com o ProactorEventLoop, o padrão do
    # Windows. O uvicorn só usa o SelectorEventLoop quando roda com --reload.
    proactor = getattr(asyncio, "ProactorEventLoop", None)
    if proactor and isinstance(asyncio.get_running_loop(), proactor):
        raise RuntimeError(
            "O banco exige o SelectorEventLoop no Windows. "
            "Rode com: uv run uvicorn src.server.app:app --reload"
        )
    try:
        redis = await cache.connect()
    except Exception as error:
        raise RuntimeError(
            f"Redis indisponível em REDIS_URL ({type(error).__name__}). "
            "Suba os serviços com: docker compose up -d"
        ) from error

    async with create_pool() as pool:
        # Com o banco atrás do código, as falhas só apareceriam no meio do uso
        # (uma coluna ou função que não existe); melhor não subir.
        if pending := await pending_migrations(pool):
            raise RuntimeError(
                f"Migrations pendentes: {', '.join(pending)}. Aplique com: uv run db/migrate.py"
            )

        saver = AsyncPostgresSaver(pool)
        await saver.setup()

        interrupted = await conversations.interrupt_streaming(pool)
        if interrupted:
            logger.info("%d mensagem(ns) em geração marcada(s) como interrompida(s)", interrupted)
        if recovered := await streams.recover(redis):
            logger.info("%d stream(s) do processo anterior encerrado(s)", recovered)
        # Memórias que ficaram sem embedding: em segundo plano, sem atrasar a subida.
        memory_processing.spawn(memory_processing.backfill(pool))

        app.state.pool = pool
        app.state.redis = redis
        # O servidor MCP, montado nesta mesma app, usa o pool daqui. O grafo
        # conhece as ferramentas pela listagem dele.
        mcp_server.attach(pool)
        setup = await load_agent()
        app.state.graph = compile_graph(saver, setup.tools, setup.sections)
        # Os turnos em andamento, que rodam fora das conexões HTTP.
        app.state.turns = set()

        purge = asyncio.create_task(_purge_expired(pool, saver))
        try:
            # A app do MCP é montada, e uma app montada não roda o próprio
            # lifespan: o gerenciador de sessões dela é aberto aqui.
            async with mcp_server.server.session_manager.run():
                yield
        finally:
            purge.cancel()
            # Cancelados, os turnos gravam o que tinham como interrompido e
            # fecham os seus streams antes de o pool e o Redis fecharem.
            for task in app.state.turns:
                task.cancel()
            await asyncio.gather(*app.state.turns, return_exceptions=True)
            # O que sobrar depois disso é embedding, que o backfill completa.
            await memory_processing.drain(timeout=10)
            mcp_server.attach(None)
            await cache.close()


app = FastAPI(title="Graham Agent", description="Seu corretor de confiança", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(keys.router)
app.include_router(agent.router)


class RenameRequest(BaseModel):
    """O título novo de uma conversa."""

    title: str = Field(min_length=1, max_length=MAX_TITLE)

    @field_validator("title")
    @classmethod
    def _clean(cls, value: str) -> str:
        title = " ".join(value.split())
        if not title:
            raise ValueError("O título não pode ficar vazio.")
        return title


class ForkRequest(BaseModel):
    """Cria uma conversa nova que continua a partir de uma mensagem."""

    message_id: UUID = Field(description="Mensagem a partir da qual a nova conversa segue.")


async def _require_thread(request: Request, thread_id: UUID) -> dict[str, Any]:
    thread = await conversations.get_thread(request.app.state.pool, thread_id, await require_user(request))
    if thread is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return thread


async def _require_on_path(request: Request, thread_id: UUID, message_id: UUID) -> list[dict[str, Any]]:
    """O caminho da thread até a mensagem, desde que ela esteja no caminho ativo."""
    path = await conversations.thread_path(request.app.state.pool, thread_id)
    for index, row in enumerate(path):
        if row["id"] == message_id:
            return path[: index + 1]
    raise HTTPException(status_code=404, detail="Mensagem fora desta conversa.")


# ─────────────────────────────────── Rotas ──────────────────────────────────


@app.post("/api/threads/{thread_id}/fork")
async def fork(thread_id: UUID, body: ForkRequest, request: Request) -> dict[str, str]:
    """Cria uma conversa que continua a partir da mensagem, sem copiar o histórico."""
    thread = await _require_thread(request, thread_id)
    await _require_on_path(request, thread_id, body.message_id)

    fork_id = await conversations.fork_thread(
        request.app.state.pool, thread["user_id"], thread["title"], body.message_id
    )
    return {"id": str(fork_id)}


def _fold(text: str) -> str:
    """Minúsculas e sem acentos, como o `unaccent` + `ILIKE` da busca."""
    return "".join(
        char for char in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(char)
    )


def _snippet(content: str, query: str) -> dict[str, str] | None:
    """O trecho da mensagem em volta do texto buscado, em três partes para a
    interface destacar a do meio sem montar HTML."""
    folded, origin = [], []
    for index, char in enumerate(content):
        for piece in _fold(char):
            folded.append(piece)
            origin.append(index)
    needle = _fold(query)
    at = "".join(folded).find(needle)
    if at < 0 or not needle:
        return None
    start, end = origin[at], origin[at + len(needle) - 1] + 1
    left, right = max(0, start - SNIPPET_RADIUS), min(len(content), end + SNIPPET_RADIUS)

    # Sem a marcação do Markdown, que no trecho solto só atrapalha a leitura.
    def plain(text: str) -> str:
        return " ".join(re.sub(r"[*#`|>]+", "", text).split())

    before, after = plain(content[left:start]), plain(content[end:right])
    return {
        "before": ("…" if left > 0 else "") + (before + " " if before and content[start - 1].isspace() else before),
        "match": content[start:end],
        "after": (" " + after if after and content[end].isspace() else after) + ("…" if right < len(content) else ""),
    }


@app.get("/api/threads")
async def list_threads(
    request: Request,
    q: str | None = Query(default=None, max_length=100, description="Texto a buscar no título e nas mensagens."),
) -> dict[str, Any]:
    """As conversas do usuário para a aba lateral, as mais recentes primeiro."""
    query = " ".join(q.split()) if q else None
    rows = await conversations.list_threads(
        request.app.state.pool, await require_user(request), MAX_THREADS, query or None
    )
    busy = await streams.busy(request.app.state.redis, [row["id"] for row in rows])
    return {
        "threads": [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "is_fork": row["is_fork"],
                "updated_at": row["updated_at"].isoformat(),
                # Respondendo agora, ou parada à espera de uma confirmação.
                "status": "streaming" if row["id"] in busy
                else "awaiting_approval" if row["head_state"] == "awaiting_approval"
                else None,
                "snippet": _snippet(row["match"], query) if query and row["match"] else None,
            }
            for row in rows
        ]
    }


@app.patch("/api/threads/{thread_id}")
async def rename_thread(thread_id: UUID, body: RenameRequest, request: Request) -> dict[str, str]:
    renamed = await conversations.rename_thread(
        request.app.state.pool, thread_id, await require_user(request), body.title
    )
    if not renamed:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return {"id": str(thread_id), "title": body.title}


@app.delete("/api/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: UUID, request: Request) -> None:
    """Apaga a conversa da lista e da memória do agente."""
    thread = await _require_thread(request, thread_id)
    # Apagar no meio de uma resposta deixaria o turno gravando numa conversa
    # que não existe mais para o usuário.
    if await streams.busy(request.app.state.redis, [thread["id"]]):
        raise HTTPException(
            status_code=409, detail="Espere a resposta em andamento terminar para apagar a conversa."
        )
    await conversations.delete_thread(request.app.state.pool, thread_id, thread["user_id"])


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    """Confirma que o grafo foi compilado e quantas ferramentas estão ligadas."""
    return {"status": "ok", "nodes": list(request.app.state.graph.get_graph().nodes)}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers=REVALIDATE)


# Sem isto, o navegador escolhe sozinho por quanto tempo reaproveitar uma cópia
# antiga do JavaScript, e a interface fica para trás do servidor. `no-cache`
# não desliga o cache: obriga a conferir a etag, e o que não mudou volta 304.
REVALIDATE = {"Cache-Control": "no-cache"}


class RevalidatedStaticFiles(StaticFiles):
    """Arquivos estáticos que o navegador confere com o servidor antes de usar."""

    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        response.headers.update(REVALIDATE)
        return response


app.mount("/static", RevalidatedStaticFiles(directory=STATIC_DIR), name="static")


# O servidor MCP, em /mcp, com os metadados de autorização em /.well-known.
# Montado na raiz e por último: só recebe o que nenhuma rota acima atendeu.
app.mount("/", mcp_server.app)
