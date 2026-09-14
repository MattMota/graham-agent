"""Servidor HTTP do Graham: serve a interface e transmite as respostas do agente."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.agent.runtime.state_graph import RE_ACT_GRAPH, AgentState

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Graham Agent", description="Seu corretor de confiança")


class ChatRequest(BaseModel):
    """Uma pergunta do usuário dentro de uma conversa."""

    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(
        min_length=1,
        max_length=100,
        description="Identifica a conversa; o checkpointer guarda o histórico por thread.",
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    """Formata um evento no protocolo Server-Sent Events."""
    # `json.dumps` escapa quebras de linha, então o payload nunca quebra o frame.
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_answer(message: str, thread_id: str) -> AsyncIterator[str]:
    """Traduz os eventos do grafo em eventos SSE para o navegador."""
    config = {"configurable": {"thread_id": thread_id}}
    entrada: AgentState = {"messages": [HumanMessage(message)]}
    # Mesmo cuidado do CLI: o modelo emite espaços em branco antes de anunciar
    # uma ferramenta, e eles não devem aparecer na tela.
    comecou = False

    try:
        async for event in RE_ACT_GRAPH.astream_events(entrada, config=config, version="v2"):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    if not comecou and not chunk.content.strip():
                        continue
                    comecou = True
                    yield _sse("token", {"text": chunk.content})

            elif kind == "on_tool_start":
                yield _sse(
                    "tool_start",
                    {"name": event["name"], "input": event["data"].get("input")},
                )

            elif kind == "on_tool_end":
                comecou = False
                yield _sse("tool_end", {"name": event["name"]})

    except Exception as error:  # noqa: BLE001 - o erro precisa chegar à interface
        yield _sse("error", {"message": f"{type(error).__name__}: {error}"})

    yield _sse("done", {})


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Responde a uma pergunta transmitindo os tokens conforme são gerados."""
    return StreamingResponse(
        _stream_answer(request.message, request.thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Impede que proxies (nginx e afins) segurem o corpo em buffer.
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Confirma que o grafo foi compilado e quantas ferramentas estão ligadas."""
    return {"status": "ok", "nodes": list(RE_ACT_GRAPH.get_graph().nodes)}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
