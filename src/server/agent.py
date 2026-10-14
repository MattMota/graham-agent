"""As rotas do agente, no protocolo AG-UI.

    POST /api/agent                    executa (`RunAgentInput`) e transmite em SSE
    POST /api/agent/connect            o snapshot da conversa e a execução em andamento
    GET  /api/agent/runs/{id}/events   retoma a leitura de uma execução

Só a nossa interface usa estas rotas, com o cookie da sessão: o Graham Agent
fica na plataforma. Para fora, o servidor MCP expõe as ferramentas. O resto
(listar, renomear, apagar e bifurcar conversas, chaves, conta) continua REST.
"""

from collections.abc import AsyncIterator, Iterable
from typing import Any
from uuid import UUID, uuid4

from ag_ui.core import (
    PROTOCOL_VERSION,
    BaseEvent,
    MessagesSnapshotEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
)
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.server import agui, runs, streams
from src.server.agui import APPROVAL_TITLES, LOCKED_FIELDS, InvalidInput, extras
from src.server.auth import require_user
from src.server.recorder import TurnRecorder
from src.storage import conversations
from src.storage.history import to_langchain
from src.tools.catalog import BY_NAME

router = APIRouter(prefix="/api/agent")

# O id de um evento no stream do Redis, para retomar a leitura depois dele.
EVENT_ID = r"^\d+(-\d+)?$"


# Respostas ──────────────────────────────────────────────────────────────────


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


async def _frames(events: Iterable[BaseEvent]) -> AsyncIterator[str]:
    for event in events:
        yield streams.frame(streams.encode(event))


def _refuse(body: RunAgentInput, code: str, message: str) -> StreamingResponse:
    """Uma entrada que o protocolo manda recusar com `RUN_ERROR`, sem executar nada."""
    return _event_stream(_frames([
        RunStartedEvent(thread_id=body.thread_id, run_id=body.run_id, protocol_version=PROTOCOL_VERSION),
        RunErrorEvent(message=message, code=code),
    ]))


def _launch(
    request: Request, thread: dict[str, Any], stream_id: str, events: AsyncIterator[BaseEvent]
) -> StreamingResponse:
    """Põe a execução para rodar em segundo plano e devolve a leitura do stream dela.

    Se o cliente desconectar, só a leitura acaba; a execução segue até o fim.
    """
    app = request.app
    streams.spawn(app.state.turns, streams.produce(app.state.redis, thread["id"], stream_id, events))
    return _event_stream(streams.consume(app.state.redis, stream_id))


# Confirmação ────────────────────────────────────────────────────────────────


class _Refused(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _validated_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Valida os valores que o usuário aprovou com o mesmo schema da ferramenta."""
    schema = BY_NAME[name].input_model
    try:
        return schema.model_validate(args).model_dump(mode="json")
    except ValidationError as error:
        titles = {key: field.title or key for key, field in schema.model_fields.items()}
        problems = "; ".join(
            f"{titles.get(str(problem['loc'][0]), problem['loc'][0])}: {problem['msg']}"
            if problem["loc"] else problem["msg"]
            for problem in error.errors()
        )
        raise _Refused("invalid_args", problems) from None


def _answers(body: RunAgentInput, pause: dict[str, Any] | None) -> dict[str, Any] | None:
    """As respostas às interrupções abertas, por tool call.

    A especificação pede que toda entrada numa conversa com interrupções
    abertas responda a todas elas, sem retomada parcial.
    """
    entries = {entry.interrupt_id: entry for entry in body.resume or []}
    if pause is None:
        return None
    requests = pause["payload"]["approval"]["requests"]
    missing = [item for item in requests if item["tool_call_id"] not in entries]
    if missing:
        titles = ", ".join(APPROVAL_TITLES.get(item["name"], item["name"]) for item in missing)
        raise _Refused(
            "pending_interrupts" if not entries else "incomplete_resume",
            f"Há uma confirmação pendente nesta conversa; responda ou cancele: {titles}.",
        )
    return entries


def _decisions(pause: dict[str, Any], entries: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """As decisões do usuário no formato que o nó de aprovação do grafo recebe."""
    decisions: dict[str, dict[str, Any]] = {}
    for item in pause["payload"]["approval"]["requests"]:
        entry = entries[item["tool_call_id"]]
        payload = entry.payload if isinstance(entry.payload, dict) else {}
        if entry.status != "resolved" or not payload.get("approved"):
            decisions[item["tool_call_id"]] = {"approved": False}
            continue
        edited = payload.get("editedArgs")
        # `editedArgs` substitui os argumentos inteiros, como manda o padrão.
        args = edited if isinstance(edited, dict) else item["args"]
        # Os campos travados valem como o agente os propôs, mande o cliente o que mandar.
        args = {**args, **{field: item["args"][field] for field in LOCKED_FIELDS if field in item["args"]}}
        decisions[item["tool_call_id"]] = {"approved": True, "args": _validated_args(item["name"], args)}
    return decisions


async def _abandon(pool, pause: dict[str, Any] | None) -> None:
    """Uma pergunta nova (ou uma regeneração) no lugar da resposta ao cartão
    encerra a confirmação pendente: as operações não são feitas."""
    if pause is not None:
        await conversations.revise_message(pool, pause["id"], state="interrupted")


# Rotas ──────────────────────────────────────────────────────────────────────


@router.post("")
async def run_agent(body: RunAgentInput, request: Request) -> StreamingResponse:
    """Executa o agente: uma pergunta nova, uma regeneração ou a resposta a uma confirmação."""
    user_id = await require_user(request)
    pool = request.app.state.pool
    try:
        thread_id = agui.uuid(body.thread_id, "threadId")
        run_id = agui.uuid(body.run_id, "runId")
        question = agui.question(body)
        regenerate = agui.regenerate_target(body)
    except InvalidInput as error:
        raise HTTPException(status_code=422, detail=str(error)) from None

    # O cliente costuma reenviar o histórico: a última mensagem só é pergunta
    # nova se ainda não estiver gravada.
    if question is not None and await conversations.get_message(pool, UUID(question.id)):
        question = None
    if question is not None and regenerate is not None:
        raise HTTPException(status_code=422, detail="Mande uma pergunta nova ou uma regeneração, não as duas.")
    try:
        content = agui.text(question) if question is not None else None
    except InvalidInput as error:
        raise HTTPException(status_code=422, detail=str(error)) from None

    thread = await conversations.get_thread(pool, thread_id, user_id)
    if thread is None and content is not None:
        # Uma conversa nova: o id veio do cliente, e o título, da pergunta.
        title = content.strip().splitlines()[0][: conversations.MAX_TITLE]
        thread = await conversations.ensure_thread(pool, thread_id, user_id, title)
    if thread is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")

    path = await conversations.thread_path(pool, thread_id)
    pause = path[-1] if path and path[-1]["state"] == "awaiting_approval" else None

    try:
        entries = _answers(body, pause)
        if content is None and regenerate is None:
            if not body.resume:
                raise _Refused("no_input", "Nada a fazer: mande uma pergunta, uma regeneração ou a resposta à confirmação.")
            if pause is None:
                raise _Refused("no_pending", "Esta confirmação não está mais pendente.")
            if all(entry.status == "cancelled" for entry in entries.values()):
                # Abandonada sem resposta: as operações não são feitas.
                await _abandon(pool, pause)
                return _event_stream(_frames([
                    RunStartedEvent(thread_id=body.thread_id, run_id=body.run_id, protocol_version=PROTOCOL_VERSION),
                    RunFinishedEvent(
                        thread_id=body.thread_id, run_id=body.run_id, metadata=extras(messageId=str(pause["id"]))
                    ),
                ]))
            return await _resume(request, thread, path, pause, _decisions(pause, entries), str(run_id))
        if entries and any(entry.status == "resolved" for entry in entries.values()):
            raise _Refused(
                "pending_interrupts",
                "Responda à confirmação pendente ou cancele-a junto da pergunta nova.",
            )
    except _Refused as refused:
        return _refuse(body, refused.code, refused.message)

    if regenerate is not None:
        return await _regenerate(request, thread, path, pause, regenerate, str(run_id))
    return await _ask(request, thread, pause, UUID(question.id), content, str(run_id))


async def _reserve(request: Request, thread: dict[str, Any], run_id: str) -> str:
    try:
        return await streams.reserve(request.app.state.redis, thread["id"], thread["user_id"], UUID(run_id))
    except streams.ThreadBusy:
        raise HTTPException(status_code=409, detail="Já há uma resposta em andamento nesta conversa.") from None
    except streams.RunExists:
        raise HTTPException(status_code=409, detail="Este runId já foi usado.") from None


async def _start(
    request: Request, thread: dict[str, Any], question_id: UUID, run_id: str
) -> AsyncIterator[BaseEvent]:
    """Começa um turno respondendo à pergunta, com o histórico até ela."""
    pool = request.app.state.pool
    graph_input = {"messages": to_langchain(await conversations.message_path(pool, question_id))}
    recorder = await TurnRecorder.start(pool, thread["id"], question_id)
    async for event in runs.run(request.app, thread, recorder, graph_input, run_id):
        yield event


async def _ask(
    request: Request,
    thread: dict[str, Any],
    pause: dict[str, Any] | None,
    question_id: UUID,
    content: str,
    run_id: str,
) -> StreamingResponse:
    pool, redis = request.app.state.pool, request.app.state.redis
    # A reserva vem antes de qualquer escrita: com outra execução em andamento,
    # a pergunta nem chega a ser gravada.
    stream_id = await _reserve(request, thread, run_id)
    try:
        await _abandon(pool, pause)
        await conversations.add_message(
            pool, thread["id"], thread["head_message_id"], "user", "completed",
            content=content, message_id=question_id,
        )
        await streams.describe(redis, thread["id"], stream_id, question_id)
    except BaseException:
        await streams.release(redis, thread["id"], stream_id)
        raise
    return _launch(request, thread, stream_id, _start(request, thread, question_id, run_id))


async def _regenerate(
    request: Request,
    thread: dict[str, Any],
    path: list[dict[str, Any]],
    pause: dict[str, Any] | None,
    message_id: UUID,
    run_id: str,
) -> StreamingResponse:
    """Gera outra resposta para a pergunta do turno, como irmã da anterior."""
    index = next((index for index, row in enumerate(path) if row["id"] == message_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Mensagem fora desta conversa.")
    question = next((row for row in reversed(path[: index + 1]) if row["role"] == "user"), None)
    if question is None:
        raise HTTPException(status_code=400, detail="Não há pergunta antes desta mensagem.")

    redis = request.app.state.redis
    stream_id = await _reserve(request, thread, run_id)
    try:
        await _abandon(request.app.state.pool, pause)
        await streams.describe(redis, thread["id"], stream_id, question["id"])
    except BaseException:
        await streams.release(redis, thread["id"], stream_id)
        raise
    return _launch(request, thread, stream_id, _start(request, thread, question["id"], run_id))


async def _resume(
    request: Request,
    thread: dict[str, Any],
    path: list[dict[str, Any]],
    pause: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
    run_id: str,
) -> StreamingResponse:
    """Retoma um turno pausado com a decisão do usuário sobre cada operação."""
    pool = request.app.state.pool
    # O turno começa na primeira mensagem depois da última pergunta; o id dela
    # nomeia a thread do LangGraph onde o grafo está esperando.
    question_index = max(index for index, row in enumerate(path) if row["role"] == "user")
    first_id = path[question_index + 1]["id"]
    snapshot = await request.app.state.graph.aget_state({"configurable": {"thread_id": str(first_id)}})
    if not snapshot.interrupts:
        await conversations.revise_message(pool, pause["id"], state="interrupted")
        raise _Refused(
            "expired", "A confirmação expirou e as operações não foram feitas. Peça de novo ao agente."
        )

    redis = request.app.state.redis
    stream_id = await _reserve(request, thread, run_id)
    try:
        requests = pause["payload"]["approval"]["requests"]
        await conversations.revise_message(
            pool, pause["id"], state="completed",
            payload={"approval": {"requests": requests, "decisions": decisions}},
        )
        await streams.describe(redis, thread["id"], stream_id, pause["id"])
    except BaseException:
        await streams.release(redis, thread["id"], stream_id)
        raise
    recorder = TurnRecorder.resume(pool, thread["id"], first_id, pause["id"], pause["parent_id"])
    events = runs.run(request.app, thread, recorder, Command(resume=decisions), run_id)
    return _launch(request, thread, stream_id, events)


class ConnectInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    thread_id: UUID = Field(alias="threadId")


@router.post("/connect")
async def connect(body: ConnectInput, request: Request) -> StreamingResponse:
    """Religa um cliente à conversa, como a rota `connect` do CopilotKit.

    Primeiro uma execução que só ressincroniza: o `MESSAGES_SNAPSHOT` do
    caminho gravado e, se a conversa espera confirmação, o fim com as
    interrupções abertas. Depois, havendo uma execução em andamento, os eventos
    dela desde o começo; o histórico para na mensagem a partir da qual ela
    escreve, para nada aparecer duas vezes.
    """
    user_id = await require_user(request)
    pool, redis = request.app.state.pool, request.app.state.redis
    thread = await conversations.get_thread(pool, body.thread_id, user_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")

    path = await conversations.thread_path(pool, body.thread_id)
    live = await streams.active(redis, body.thread_id)
    if live:
        for index, row in enumerate(path):
            if str(row["id"]) == live["after_message_id"]:
                path = path[: index + 1]
                break

    thread_id, sync_id = str(body.thread_id), str(uuid4())
    forked_from = thread["forked_from_message_id"]
    sync = [
        RunStartedEvent(thread_id=thread_id, run_id=sync_id, protocol_version=PROTOCOL_VERSION),
        MessagesSnapshotEvent(
            messages=agui.snapshot(path),
            metadata=extras(
                title=thread["title"],
                forkedFromMessageId=str(forked_from) if forked_from else None,
                # A execução em andamento, que vem em seguida e continua daqui.
                activeRunId=live["id"] if live else None,
            ),
        ),
        RunFinishedEvent(thread_id=thread_id, run_id=sync_id, outcome=None if live else agui.pending(path)),
    ]

    async def events() -> AsyncIterator[str]:
        async for frame in _frames(sync):
            yield frame
        if live:
            async for frame in streams.consume(redis, live["id"]):
                yield frame

    return _event_stream(events())


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: UUID,
    request: Request,
    after: str | None = Query(default=None, pattern=EVENT_ID, description="Último evento recebido."),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID", pattern=EVENT_ID),
) -> StreamingResponse:
    """Retoma a leitura de uma execução: os eventos depois do último recebido, ou todos."""
    user_id = await require_user(request)
    redis = request.app.state.redis
    meta = await streams.owner(redis, str(run_id))
    if meta is None or meta["user_id"] != str(user_id):
        raise HTTPException(status_code=404, detail="Execução não encontrada ou já expirada.")
    return _event_stream(streams.consume(redis, str(run_id), last_event_id or after or "0"))
