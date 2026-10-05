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
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError

from src.agent.runtime.context import AgentContext
from src.agent.runtime.state_graph import AgentState, compile_graph
from src.agent.tools.definition import get_current_stock_price
from src.agent.tools.registry import APPROVAL_REQUIRED, TOOLS
from src.server import streams
from src.server.recorder import TurnRecorder
from src.storage import cache, conversations
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

    try:
        redis = await cache.connect()
    except Exception as error:
        raise RuntimeError(
            f"Redis indisponível em REDIS_URL ({type(error).__name__}). "
            "Suba os serviços com: docker compose up -d"
        ) from error

    async with create_pool() as pool:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()

        interrupted = await conversations.interrupt_streaming(pool)
        if interrupted:
            logger.info("%d mensagem(ns) em geração marcada(s) como interrompida(s)", interrupted)
        if recovered := await streams.recover(redis):
            logger.info("%d stream(s) do processo anterior encerrado(s)", recovered)

        app.state.pool = pool
        app.state.redis = redis
        app.state.graph = compile_graph(saver)
        # Os turnos em andamento, que rodam fora das conexões HTTP.
        app.state.turns = set()

        purge = asyncio.create_task(_purge_checkpoints(pool, saver))
        try:
            yield
        finally:
            purge.cancel()
            # Cancelados, os turnos gravam o que tinham como interrompido e
            # fecham os seus streams antes de o pool e o Redis fecharem.
            for task in app.state.turns:
                task.cancel()
            await asyncio.gather(*app.state.turns, return_exceptions=True)
            await cache.close()


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


class Decision(BaseModel):
    """O que o usuário decidiu sobre uma operação."""

    tool_call_id: str
    approved: bool
    args: dict[str, Any] | None = Field(
        default=None,
        description="Os valores corrigidos pelo usuário; sem eles, valem os do agente.",
    )


class ApprovalRequest(BaseModel):
    """As decisões do usuário sobre as operações de um turno pausado."""

    thread_id: UUID
    message_id: UUID = Field(description="A mensagem que marca a pausa.")
    decisions: list[Decision]


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
    for key in ("matches", "companies", "positions", "entries"):
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


# ─────────────────────────────── Confirmação ────────────────────────────────

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}

APPROVAL_TITLES = {
    "registrar_compra": "Registrar compra na carteira",
    "registrar_venda": "Registrar venda na carteira",
    "adicionar_watchlist": "Adicionar à watchlist",
    "remover_watchlist": "Remover da watchlist",
}

# Campos que o usuário não corrige no cartão. Um ativo errado não é um valor a
# ajustar: é outra operação, então ele cancela e pede ao agente.
LOCKED_FIELDS = ("ticker_name",)


def _approval_requests(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Os pedidos de confirmação, com o que a interface precisa para montar o
    formulário: o título da operação, o schema dos argumentos e os campos travados."""
    enriched = []
    for request in requests:
        schema = TOOLS_BY_NAME[request["name"]].args_schema.model_json_schema()
        enriched.append({
            **request,
            "title": APPROVAL_TITLES.get(request["name"], request["name"]),
            "schema": schema,
            "locked": [field for field in LOCKED_FIELDS if field in schema["properties"]],
        })
    return enriched


def _validated_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Valida os valores que o usuário aprovou com o mesmo schema da ferramenta."""
    schema = TOOLS_BY_NAME[name].args_schema
    try:
        return schema.model_validate(args).model_dump(mode="json")
    except ValidationError as error:
        titles = {key: field.title or key for key, field in schema.model_fields.items()}
        problems = "; ".join(
            f"{titles.get(str(problem['loc'][0]), problem['loc'][0])}: {problem['msg']}"
            if problem["loc"] else problem["msg"]
            for problem in error.errors()
        )
        raise HTTPException(status_code=422, detail=problems) from None


async def _abandon_pending_approval(pool, thread: dict[str, Any]) -> None:
    """Uma pergunta nova (ou uma regeneração) no lugar da resposta ao cartão
    encerra a confirmação pendente: as operações não são feitas."""
    head = thread["head_message_id"]
    if head is not None:
        row = await conversations.get_message(pool, head)
        if row and row["state"] == "awaiting_approval":
            await conversations.revise_message(pool, head, state="interrupted")


# ──────────────────────────────── Execução ──────────────────────────────────


async def _run_turn(
    app: FastAPI, thread: dict[str, Any], recorder: TurnRecorder, graph_input: Any
) -> AsyncIterator[str]:
    """Executa o grafo, gravando as mensagens e traduzindo os eventos em SSE.

    Serve tanto ao começo de um turno quanto à retomada depois da confirmação:
    nos dois casos o turno pode terminar, falhar ou pausar de novo.
    """
    pool = app.state.pool
    graph = app.state.graph
    # Cada turno roda numa thread própria do LangGraph: os checkpoints servem
    # para inspecionar a execução e para esperar a confirmação; o histórico vem
    # das nossas tabelas.
    config = {
        "configurable": {"thread_id": recorder.graph_thread_id},
        "metadata": {"graham_thread_id": str(thread["id"])},
    }
    context = AgentContext(user_id=thread["user_id"], pool=pool)

    # Mesmo cuidado do CLI: o modelo emite espaços em branco antes de anunciar
    # uma ferramenta, e eles não devem aparecer na tela.
    comecou = False

    # Cotações já obtidas pelas ferramentas, e todo ticker que passou por elas.
    quotes: dict[str, dict[str, Any]] = {}
    candidates: list[str] = []
    answer = ""

    # Só vira verdadeiro quando o turno termina, falha ou pausa. Se o gerador
    # for encerrado antes disso, o cliente desconectou no meio da resposta.
    settled = False

    try:
        async for event in graph.astream_events(
            graph_input, config=config, context=context, version="v2"
        ):
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

            # As operações que pediram confirmação já têm o seu cartão na tela;
            # o resultado delas chega pelo fim do nó `tools`, mais abaixo.
            elif kind in ("on_tool_start", "on_tool_end") and event["name"] in APPROVAL_REQUIRED:
                comecou = False

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

                # O artefato (a série do gráfico do desempenho) vai só para a
                # interface; o modelo recebeu apenas o conteúdo.
                yield _sse(
                    "tool_end",
                    {
                        "name": event["name"],
                        "output": _tool_preview(payload),
                        "artifact": getattr(event["data"].get("output"), "artifact", None),
                    },
                )

            # O fim de cada nó traz as mensagens que ele acrescentou ao estado.
            elif kind == "on_chain_end" and event["name"] == "agent":
                await recorder.model_finished(event["data"]["output"]["messages"][-1])

            elif kind == "on_chain_end" and event["name"] == "approval":
                output = event["data"]["output"]
                if isinstance(output, Command) and output.update:
                    await recorder.approval_finished(output.update.get("messages", []))

            elif kind == "on_chain_end" and event["name"] == "tools":
                messages = event["data"]["output"]["messages"]
                await recorder.tools_finished(messages)
                # Daqui, e não do `on_tool_end`: um erro que escapa da
                # ferramenta é tratado pelo ToolNode e só aparece nesta saída.
                for message in messages:
                    if message.name in APPROVAL_REQUIRED:
                        failed = message.status == "error"
                        yield _sse("operation", {
                            "tool_call_id": message.tool_call_id,
                            "status": "failed" if failed else "completed",
                            "message": message.text if failed else None,
                        })

        for card in await _ticker_cards(quotes, candidates, answer):
            yield _sse("ticker", card)

        # O grafo parou no nó de aprovação: o turno espera o usuário decidir.
        snapshot = await graph.aget_state(config)
        if snapshot.interrupts:
            requests = snapshot.interrupts[0].value
            approval_id = await recorder.pause(requests)
            settled = True
            yield _sse("approval", {
                "message_id": str(approval_id),
                "requests": _approval_requests(requests),
            })
            yield _sse("done", {"message_id": str(approval_id), "state": "awaiting_approval"})
            return

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


async def _start_turn(app: FastAPI, thread: dict[str, Any], question_id: UUID) -> AsyncIterator[str]:
    """Começa um turno respondendo à pergunta, com o histórico até ela."""
    pool = app.state.pool
    yield _sse("thread", {"id": str(thread["id"]), "title": thread["title"]})

    entrada: AgentState = {
        "messages": to_langchain(await conversations.message_path(pool, question_id))
    }
    recorder = await TurnRecorder.start(pool, thread["id"], question_id)
    async for frame in _run_turn(app, thread, recorder, entrada):
        yield frame


async def _resume_turn(
    app: FastAPI, thread: dict[str, Any], recorder: TurnRecorder, decisions: dict[str, Any]
) -> AsyncIterator[str]:
    """Retoma um turno pausado, entregando ao grafo as decisões do usuário."""
    yield _sse("thread", {"id": str(thread["id"]), "title": thread["title"]})
    async for frame in _run_turn(app, thread, recorder, Command(resume=decisions)):
        yield frame


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
    # Resultado de cada operação confirmada ou cancelada, por tool call.
    results: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = row["payload"] or {}
        if row["role"] == "assistant":
            if row["content"]:
                blocks.append({"type": "text", "text": row["content"]})
            for call in payload.get("tool_calls") or []:
                # As operações aparecem no cartão de confirmação, não como consulta.
                if call["name"] in APPROVAL_REQUIRED:
                    continue
                tools[call["id"]] = {
                    "type": "tool",
                    "name": call["name"],
                    "input": call["args"],
                    "output": None,
                    "done": False,
                }
                blocks.append(tools[call["id"]])
            if approval := payload.get("approval"):
                blocks.append({
                    "type": "approval",
                    "message_id": str(row["id"]),
                    "state": row["state"],
                    "requests": _approval_requests(approval["requests"]),
                    "decisions": approval.get("decisions"),
                    "results": results,
                })
        elif payload.get("tool_call_id") in tools:
            tools[payload["tool_call_id"]].update(
                output=_tool_preview(_tool_payload(row["content"])),
                artifact=payload.get("artifact"),
                done=True,
            )
        elif payload.get("name") in APPROVAL_REQUIRED:
            failed = row["state"] == "failed" and not payload.get("cancelled")
            results[payload["tool_call_id"]] = {
                "status": "cancelled" if payload.get("cancelled") else row["state"],
                "message": row["content"] if failed else None,
            }

    last = rows[-1]
    # Um turno que parou entre uma ferramenta e outra, sem a mensagem que o
    # fecha, também conta como interrompido — inclusive logo depois de uma
    # confirmação, antes de as operações rodarem.
    finished = last["role"] == "assistant" and not (last["payload"] or {}).get("tool_calls")
    state = last["state"] if finished else "interrupted"
    if (last["payload"] or {}).get("approval") and state == "completed":
        state = "interrupted"
    return {"role": "assistant", "id": str(last["id"]), "state": state, "blocks": blocks}


async def _reserve(request: Request, thread: dict[str, Any]) -> str:
    try:
        return await streams.reserve(request.app.state.redis, thread["id"], thread["user_id"])
    except streams.ThreadBusy:
        raise HTTPException(
            status_code=409, detail="Já há uma resposta em andamento nesta conversa."
        ) from None


def _launch(
    request: Request, thread: dict[str, Any], stream_id: str, frames: AsyncIterator[str]
) -> StreamingResponse:
    """Põe o turno para rodar em segundo plano e devolve a leitura do stream dele.

    Se o navegador desconectar, só a leitura acaba; o turno segue até o fim.
    """
    app = request.app
    streams.spawn(app.state.turns, streams.produce(app.state.redis, thread["id"], stream_id, frames))
    return _event_stream(streams.consume(app.state.redis, stream_id))


# ─────────────────────────────────── Rotas ──────────────────────────────────


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
    pool, redis = request.app.state.pool, request.app.state.redis
    if body.thread_id is None:
        title = body.message.strip().splitlines()[0][:MAX_TITLE]
        thread = await conversations.create_thread(pool, _require_user(request), title)
    else:
        thread = await _require_thread(request, body.thread_id)

    # A reserva vem antes de qualquer escrita: com outro turno em andamento,
    # a pergunta nem chega a ser gravada.
    stream_id = await _reserve(request, thread)
    try:
        await _abandon_pending_approval(pool, thread)
        question_id = await conversations.add_message(
            pool, thread["id"], thread["head_message_id"], "user", "completed", content=body.message
        )
        await streams.describe(redis, thread["id"], stream_id, question_id)
    except BaseException:
        await streams.release(redis, thread["id"], stream_id)
        raise
    return _launch(request, thread, stream_id, _start_turn(request.app, thread, question_id))


@app.post("/api/regenerate")
async def regenerate(body: RegenerateRequest, request: Request) -> StreamingResponse:
    """Gera outra resposta para a pergunta do turno, como irmã da anterior."""
    thread = await _require_thread(request, body.thread_id)
    path = await _require_on_path(request, body.thread_id, body.message_id)

    question = next((row for row in reversed(path) if row["role"] == "user"), None)
    if question is None:
        raise HTTPException(status_code=400, detail="Não há pergunta antes desta mensagem.")

    redis = request.app.state.redis
    stream_id = await _reserve(request, thread)
    try:
        await _abandon_pending_approval(request.app.state.pool, thread)
        await streams.describe(redis, thread["id"], stream_id, question["id"])
    except BaseException:
        await streams.release(redis, thread["id"], stream_id)
        raise
    return _launch(request, thread, stream_id, _start_turn(request.app, thread, question["id"]))


@app.post("/api/approvals")
async def approve(body: ApprovalRequest, request: Request) -> StreamingResponse:
    """Retoma um turno pausado com a decisão do usuário sobre cada operação."""
    pool = request.app.state.pool
    thread = await _require_thread(request, body.thread_id)
    path = await conversations.thread_path(pool, body.thread_id)

    pause = path[-1] if path else None
    if pause is None or pause["id"] != body.message_id or pause["state"] != "awaiting_approval":
        raise HTTPException(status_code=409, detail="Esta confirmação não está mais pendente.")

    requests = pause["payload"]["approval"]["requests"]
    decided = {decision.tool_call_id: decision for decision in body.decisions}
    decisions: dict[str, dict[str, Any]] = {}
    for item in requests:
        decision = decided.get(item["tool_call_id"])
        if decision is None:
            title = APPROVAL_TITLES.get(item["name"], item["name"])
            raise HTTPException(status_code=422, detail=f"Falta decidir: {title}.")
        if decision.approved:
            args = decision.args if decision.args is not None else item["args"]
            # Os campos travados valem como o agente os propôs, mande o cliente o que mandar.
            args = {**args, **{field: item["args"][field] for field in LOCKED_FIELDS if field in item["args"]}}
            decisions[item["tool_call_id"]] = {
                "approved": True,
                "args": _validated_args(item["name"], args),
            }
        else:
            decisions[item["tool_call_id"]] = {"approved": False}

    # O turno começa na primeira mensagem depois da última pergunta; o id dela
    # nomeia a thread do LangGraph onde o grafo está esperando.
    question_index = max(index for index, row in enumerate(path) if row["role"] == "user")
    first_id = path[question_index + 1]["id"]
    snapshot = await request.app.state.graph.aget_state(
        {"configurable": {"thread_id": str(first_id)}}
    )
    if not snapshot.interrupts:
        await conversations.revise_message(pool, pause["id"], state="interrupted")
        raise HTTPException(
            status_code=410,
            detail="A confirmação expirou e as operações não foram feitas. Peça de novo ao agente.",
        )

    redis = request.app.state.redis
    stream_id = await _reserve(request, thread)
    try:
        await conversations.revise_message(
            pool,
            pause["id"],
            state="completed",
            payload={"approval": {"requests": requests, "decisions": decisions}},
        )
        await streams.describe(redis, thread["id"], stream_id, pause["id"])
    except BaseException:
        await streams.release(redis, thread["id"], stream_id)
        raise
    recorder = TurnRecorder.resume(pool, thread["id"], first_id, pause["id"], pause["parent_id"])
    return _launch(request, thread, stream_id, _resume_turn(request.app, thread, recorder, decisions))


@app.get("/api/streams/{stream_id}")
async def resume_stream(
    stream_id: UUID,
    request: Request,
    after: str = Query(default="0", pattern=r"^\d+(-\d+)?$", description="Último evento recebido."),
) -> StreamingResponse:
    """Reconecta a um turno: os eventos depois de `after`, ou todos, sem ele."""
    redis = request.app.state.redis
    meta = await streams.owner(redis, str(stream_id))
    if meta is None or meta["user_id"] != str(_require_user(request)):
        raise HTTPException(status_code=404, detail="Stream não encontrado ou já expirado.")
    return _event_stream(streams.consume(redis, str(stream_id), after))


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

    # Com um turno em andamento, o histórico para na mensagem a partir da qual
    # ele escreve; a interface redesenha o resto lendo o stream do começo, sem
    # mostrar duas vezes o que já foi gravado.
    live = await streams.active(request.app.state.redis, thread_id)
    if live:
        for index, row in enumerate(path):
            if str(row["id"]) == live["after_message_id"]:
                path = path[: index + 1]
                break

    turns = [_display_turn(turn) for turn in split_turns(path)]
    if live and turns and turns[-1]["role"] == "assistant" and turns[-1]["id"] == live["after_message_id"]:
        # A retomada depois de uma confirmação continua este mesmo turno.
        turns[-1]["state"] = "streaming"

    forked_from = thread["forked_from_message_id"]
    return _json_safe({
        "id": str(thread["id"]),
        "title": thread["title"],
        "forked_from_message_id": str(forked_from) if forked_from else None,
        "turns": turns,
        "active_stream": {"id": live["id"], "after_message_id": live["after_message_id"]} if live else None,
    })


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
