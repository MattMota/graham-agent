"""Servidor HTTP do Graham: serve a interface, grava as conversas e transmite
as respostas do agente."""

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field

from src.agent.runtime.state_graph import AgentState, compile_graph
from src.agent.tools.definition import get_current_stock_price
from src.server.recorder import TurnRecorder
from src.storage import conversations
from src.storage.database import create_pool
from src.storage.history import split_turns, to_langchain

STATIC_DIR = Path(__file__).parent / "static"

# Quantos cartões de ticker podem ser enviados ao final de uma resposta.
MAX_TICKER_CARDS = 8

# Teto para o retorno da ferramenta exibido na interface, em caracteres.
MAX_TOOL_PREVIEW = 20_000

# Por quanto tempo os checkpoints de um turno ficam guardados para inspeção.
CHECKPOINT_RETENTION = timedelta(days=1)

# De quanto em quanto tempo os checkpoints vencidos são apagados.
PURGE_INTERVAL = timedelta(hours=1)

# Tamanho máximo do título, tirado da primeira pergunta da conversa.
MAX_TITLE = 80

USER_COOKIE = "graham_user"
USER_COOKIE_MAX_AGE = int(timedelta(days=365).total_seconds())

logger = logging.getLogger("uvicorn.error")


async def _purge_checkpoints(pool, saver: AsyncPostgresSaver) -> None:
    """Apaga, de hora em hora, os checkpoints dos turnos que passaram da retenção."""
    while True:
        try:
            for graph_thread_id in await conversations.expired_graph_threads(pool, CHECKPOINT_RETENTION):
                await saver.adelete_thread(graph_thread_id)
        except Exception:  # noqa: BLE001 - uma falha na limpeza não pode derrubar o servidor
            logger.exception("Falha ao apagar checkpoints vencidos")
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
    if not os.getenv("SESSION_SECRET"):
        raise RuntimeError("Defina SESSION_SECRET no .env para assinar o cookie do usuário.")

    async with create_pool() as pool:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()

        interrupted = await conversations.interrupt_streaming(pool)
        if interrupted:
            logger.info("%d mensagem(ns) em geração marcada(s) como interrompida(s)", interrupted)

        app.state.pool = pool
        app.state.graph = compile_graph(saver)

        purge = asyncio.create_task(_purge_checkpoints(pool, saver))
        try:
            yield
        finally:
            purge.cancel()


app = FastAPI(title="Graham Agent", description="Seu corretor de confiança", lifespan=lifespan)


class ChatRequest(BaseModel):
    """Uma pergunta do usuário dentro de uma conversa."""

    message: str = Field(min_length=1, max_length=4000)
    thread_id: UUID | None = Field(
        default=None,
        description="Conversa a continuar; sem ela, uma nova é criada.",
    )


class RegenerateRequest(BaseModel):
    """Pede uma nova resposta para um turno da conversa."""

    thread_id: UUID
    message_id: UUID = Field(description="Qualquer mensagem do turno a regerar.")


class ForkRequest(BaseModel):
    """Cria uma conversa nova que continua a partir de uma mensagem."""

    message_id: UUID = Field(description="Mensagem a partir da qual a nova conversa segue.")


# ─────────────────────────────── Usuário anônimo ────────────────────────────


def _sign(user_id: UUID) -> str:
    """Valor do cookie: o id do usuário seguido de um HMAC dele."""
    secret = os.environ["SESSION_SECRET"].encode()
    digest = hmac.new(secret, str(user_id).encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{digest}"


def _verify(cookie: str | None) -> UUID | None:
    """O id do usuário, se o cookie existir e a assinatura conferir."""
    if not cookie or "." not in cookie:
        return None
    try:
        user_id = UUID(cookie.split(".", 1)[0])
    except ValueError:
        return None
    return user_id if hmac.compare_digest(cookie, _sign(user_id)) else None


def _require_user(request: Request) -> UUID:
    user_id = _verify(request.cookies.get(USER_COOKIE))
    if user_id is None:
        raise HTTPException(status_code=401, detail="Sessão ausente; chame /api/session.")
    return user_id


async def _require_thread(request: Request, thread_id: UUID) -> dict[str, Any]:
    thread = await conversations.get_thread(request.app.state.pool, thread_id, _require_user(request))
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


def _json_safe(value: Any) -> Any:
    """Troca NaN e Infinity por `None` em toda a estrutura.

    `json.dumps` os escreve como literais `NaN`/`Infinity`, que não existem no
    JSON e derrubam o `JSON.parse` do navegador — junto com a resposta inteira.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _sse(event: str, data: dict[str, Any]) -> str:
    """Formata um evento no protocolo Server-Sent Events."""
    # `json.dumps` escapa quebras de linha, então o payload nunca quebra o frame.
    return (
        f"event: {event}\n"
        f"data: {json.dumps(_json_safe(data), ensure_ascii=False, allow_nan=False)}\n\n"
    )


def _tool_payload(output: Any) -> Any:
    """Extrai o dado que a ferramenta devolveu de dentro do ToolMessage."""
    content = getattr(output, "content", output)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    return content


def _tool_preview(payload: Any) -> Any:
    """Prepara o retorno da ferramenta para exibição, limitando o tamanho."""
    if payload is None:
        return None
    serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized) > MAX_TOOL_PREVIEW:
        return {
            "aviso": "Resultado longo demais para exibir por inteiro.",
            "caracteres": len(serialized),
        }
    return payload


def _ticker_card(quote: dict[str, Any]) -> dict[str, Any]:
    """Reduz uma cotação completa aos campos que o cartão mostra."""
    return {
        "symbol": quote.get("ticker_name"),
        "name": quote.get("company_name"),
        "currency": quote.get("currency"),
        "price": quote.get("price"),
        "change": quote.get("change"),
        "change_percent": quote.get("change_percent"),
        "quoted_at": quote.get("quoted_at"),
    }


def _symbols_in(payload: Any) -> list[str]:
    """Colhe os tickers que aparecem no retorno de qualquer ferramenta."""
    if not isinstance(payload, dict):
        return []

    symbols = []
    if payload.get("ticker_name"):
        symbols.append(payload["ticker_name"])
    for key in ("matches", "companies"):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and item.get("ticker_name"):
                symbols.append(item["ticker_name"])
    return symbols


def _mentioned(symbol: str, text: str) -> bool:
    """O agente citou este ticker na resposta? 'BBAS3' conta por 'BBAS3.SA'."""
    return symbol in text or symbol.split(".")[0] in text


async def _ticker_cards(
    quotes: dict[str, dict[str, Any]], candidates: list[str], answer: str
) -> list[dict[str, Any]]:
    """Monta os cartões dos tickers citados, buscando só o que ainda falta."""
    wanted = []
    for symbol in candidates:
        if symbol not in wanted and _mentioned(symbol, answer):
            wanted.append(symbol)
    wanted.sort(key=lambda symbol: answer.find(symbol.split(".")[0]))
    wanted = wanted[:MAX_TICKER_CARDS]

    missing = [symbol for symbol in wanted if symbol not in quotes]
    if missing:
        # A ferramenta é síncrona; o LangChain a roda numa thread, então as
        # consultas que faltam acontecem em paralelo e fora do event loop.
        fetched = await asyncio.gather(
            *(get_current_stock_price.ainvoke({"ticker_name": symbol}) for symbol in missing),
            return_exceptions=True,
        )
        for symbol, result in zip(missing, fetched):
            if isinstance(result, dict):
                quotes[symbol] = result

    return [_ticker_card(quotes[symbol]) for symbol in wanted if symbol in quotes]


async def _stream_answer(app: FastAPI, thread: dict[str, Any], question_id: UUID) -> AsyncIterator[str]:
    """Roda um turno do agente, gravando as mensagens e traduzindo os eventos do
    grafo em eventos SSE para o navegador."""
    pool = app.state.pool
    yield _sse("thread", {"id": str(thread["id"]), "title": thread["title"]})

    entrada: AgentState = {
        "messages": to_langchain(await conversations.message_path(pool, question_id))
    }
    recorder = await TurnRecorder.start(pool, thread["id"], question_id)
    # Cada turno roda numa thread própria do LangGraph: os checkpoints servem
    # para inspecionar a execução, e o histórico vem das nossas tabelas.
    config = {
        "configurable": {"thread_id": recorder.graph_thread_id},
        "metadata": {"graham_thread_id": str(thread["id"])},
    }

    # Mesmo cuidado do CLI: o modelo emite espaços em branco antes de anunciar
    # uma ferramenta, e eles não devem aparecer na tela.
    comecou = False

    # Cotações já obtidas pelas ferramentas, e todo ticker que passou por elas.
    quotes: dict[str, dict[str, Any]] = {}
    candidates: list[str] = []
    answer = ""

    # Só vira verdadeiro quando o turno termina, bem ou com erro. Se o gerador
    # for encerrado antes disso, o cliente desconectou no meio da resposta.
    settled = False

    try:
        async for event in app.state.graph.astream_events(entrada, config=config, version="v2"):
            kind = event["event"]

            if kind == "on_chat_model_start":
                await recorder.model_started()

            elif kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    recorder.token(chunk.content)
                    if not comecou and not chunk.content.strip():
                        continue
                    comecou = True
                    answer += chunk.content
                    yield _sse("token", {"text": chunk.content})

            elif kind == "on_tool_start":
                yield _sse(
                    "tool_start",
                    {"name": event["name"], "input": event["data"].get("input")},
                )

            elif kind == "on_tool_end":
                comecou = False

                payload = _tool_payload(event["data"].get("output"))
                # A cotação completa já vem pronta aqui: nenhum cartão que o
                # agente consultou precisa de uma segunda ida ao Yahoo.
                if event["name"] == "cotacao_atual_acao" and isinstance(payload, dict):
                    if payload.get("ticker_name"):
                        quotes[payload["ticker_name"]] = payload
                candidates.extend(_symbols_in(payload))

                yield _sse(
                    "tool_end",
                    {"name": event["name"], "output": _tool_preview(payload)},
                )

            # O fim de cada nó traz as mensagens que ele acrescentou ao estado.
            elif kind == "on_chain_end" and event["name"] == "agent":
                await recorder.model_finished(event["data"]["output"]["messages"][-1])

            elif kind == "on_chain_end" and event["name"] == "tools":
                await recorder.tools_finished(event["data"]["output"]["messages"])

        for card in await _ticker_cards(quotes, candidates, answer):
            yield _sse("ticker", card)

        settled = True
        yield _sse("done", {"message_id": str(recorder.last), "state": "completed"})

    except Exception as error:  # noqa: BLE001 - o erro precisa chegar à interface
        settled = True
        detail = f"{type(error).__name__}: {error}"
        message_id = await recorder.stop("failed", error=detail)
        yield _sse("error", {"message": detail})
        yield _sse("done", {"message_id": str(message_id), "state": "failed"})

    finally:
        if not settled:
            # O cancelamento do cliente atinge também estas escritas; o escudo
            # garante que o texto parcial seja salvo antes de o gerador fechar.
            with anyio.CancelScope(shield=True):
                await recorder.stop("interrupted")


def _event_stream(body: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Impede que proxies (nginx e afins) segurem o corpo em buffer.
            "X-Accel-Buffering": "no",
        },
    )


def _display_turn(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Prepara um turno gravado para a interface redesenhar."""
    first = rows[0]
    if first["role"] == "user":
        return {"role": "user", "id": str(first["id"]), "content": first["content"]}

    blocks: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = row["payload"] or {}
        if row["role"] == "assistant":
            if row["content"]:
                blocks.append({"type": "text", "text": row["content"]})
            for call in payload.get("tool_calls") or []:
                tools[call["id"]] = {
                    "type": "tool",
                    "name": call["name"],
                    "input": call["args"],
                    "output": None,
                    "done": False,
                }
                blocks.append(tools[call["id"]])
        elif payload.get("tool_call_id") in tools:
            tools[payload["tool_call_id"]].update(
                output=_tool_preview(_tool_payload(row["content"])), done=True
            )

    last = rows[-1]
    # Um turno que parou entre uma ferramenta e outra, sem a mensagem que o
    # fecha, também conta como interrompido.
    finished = last["role"] == "assistant" and not (last["payload"] or {}).get("tool_calls")
    state = last["state"] if finished else "interrupted"
    return {"role": "assistant", "id": str(last["id"]), "state": state, "blocks": blocks}


@app.post("/api/session")
async def session(request: Request) -> JSONResponse:
    """Garante o cookie do usuário anônimo; na primeira visita, cria o usuário."""
    pool = request.app.state.pool
    user_id = _verify(request.cookies.get(USER_COOKIE))
    if user_id is not None and await conversations.user_exists(pool, user_id):
        return JSONResponse({"status": "ok"})

    user_id = await conversations.create_user(pool)
    response = JSONResponse({"status": "created"})
    response.set_cookie(
        USER_COOKIE,
        _sign(user_id),
        max_age=USER_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    """Responde a uma pergunta transmitindo os tokens conforme são gerados."""
    pool = request.app.state.pool
    if body.thread_id is None:
        title = body.message.strip().splitlines()[0][:MAX_TITLE]
        thread = await conversations.create_thread(pool, _require_user(request), title)
    else:
        thread = await _require_thread(request, body.thread_id)

    question_id = await conversations.add_message(
        pool, thread["id"], thread["head_message_id"], "user", "completed", content=body.message
    )
    return _event_stream(_stream_answer(request.app, thread, question_id))


@app.post("/api/regenerate")
async def regenerate(body: RegenerateRequest, request: Request) -> StreamingResponse:
    """Gera outra resposta para a pergunta do turno, como irmã da anterior."""
    thread = await _require_thread(request, body.thread_id)
    path = await _require_on_path(request, body.thread_id, body.message_id)

    question = next((row for row in reversed(path) if row["role"] == "user"), None)
    if question is None:
        raise HTTPException(status_code=400, detail="Não há pergunta antes desta mensagem.")
    return _event_stream(_stream_answer(request.app, thread, question["id"]))


@app.post("/api/threads/{thread_id}/fork")
async def fork(thread_id: UUID, body: ForkRequest, request: Request) -> dict[str, str]:
    """Cria uma conversa que continua a partir da mensagem, sem copiar o histórico."""
    thread = await _require_thread(request, thread_id)
    await _require_on_path(request, thread_id, body.message_id)

    fork_id = await conversations.fork_thread(
        request.app.state.pool, thread["user_id"], thread["title"], body.message_id
    )
    return {"id": str(fork_id)}


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: UUID, request: Request) -> dict[str, Any]:
    """O caminho ativo da conversa, agrupado em turnos para a interface."""
    thread = await _require_thread(request, thread_id)
    path = await conversations.thread_path(request.app.state.pool, thread_id)
    forked_from = thread["forked_from_message_id"]
    return _json_safe({
        "id": str(thread["id"]),
        "title": thread["title"],
        "forked_from_message_id": str(forked_from) if forked_from else None,
        "turns": [_display_turn(turn) for turn in split_turns(path)],
    })


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    """Confirma que o grafo foi compilado e quantas ferramentas estão ligadas."""
    return {"status": "ok", "nodes": list(request.app.state.graph.get_graph().nodes)}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
