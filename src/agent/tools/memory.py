"""Ferramentas de memória de longo prazo.

Guardar e esquecer respondem na hora: a gravação é imediata, e o embedding e a
checagem de substituição seguem em segundo plano. Buscar e ver esperam o
resultado, porque o agente precisa dele para responder.
"""

import inspect
import sys
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool, ToolException, tool
from langgraph.prebuilt import ToolRuntime

from src.agent.memory import processing
from src.agent.memory.embeddings import embed, to_halfvec
from src.agent.tools.portfolio import _context as require_context
from src.agent.tools.schemas.memory import MemoryIdInput, RecallInput, RememberInput
from src.storage import conversations, memories

# Quantas memórias a busca devolve, e quanto de cada uma (a íntegra vem por
# ver_memoria): um turno de conversa pode ter milhares de caracteres.
SEARCH_LIMIT = 8
PREVIEW_CHARS = 400

# Retorno das ferramentas abreviado no ver_memoria de uma conversa.
TOOL_OUTPUT_CHARS = 300


def _preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


@tool(
    "guardar_memoria",
    description=(
        "Guarda um fato duradouro sobre o usuário: perfil de investidor, preferências, "
        "interesses ou um acontecimento que valha lembrar. Não use para dados de mercado. "
        "Para atualizar um fato, guarde a versão nova: a antiga é substituída sozinha."
    ),
    args_schema=RememberInput,
)
async def remember(fact: str, category: str, runtime: ToolRuntime) -> dict[str, Any]:
    context = require_context(runtime)
    row = await memories.add_memory(context.pool, context.user_id, category, fact.strip())
    processing.spawn(
        processing.process_memory(context.pool, context.user_id, row["id"], category, row["content"])
    )
    return {"memory_id": str(row["id"]), "category": category, "saved": row["content"]}


@tool(
    "buscar_memorias",
    description=(
        "Busca fatos sobre o usuário e trechos de conversas anteriores relacionados ao tema "
        "informado. Use quando a resposta depender do histórico ou das preferências do usuário."
    ),
    args_schema=RecallInput,
)
async def recall(search_fact: str, runtime: ToolRuntime) -> dict[str, Any]:
    context = require_context(runtime)
    vectors = await embed([search_fact])
    vector = to_halfvec(vectors[0]) if vectors else None
    rows = await memories.search(context.pool, context.user_id, search_fact, vector, SEARCH_LIMIT)
    output: dict[str, Any] = {
        "results": [
            {
                "memory_id": str(row["id"]),
                "category": row["category"],
                "date": row["created_at"].date().isoformat(),
                "content": _preview(row["content"]),
            }
            for row in rows
        ]
    }
    if vector is None:
        output["note"] = "Busca feita só por palavras: o serviço de embedding não respondeu."
    return output


async def _turn_messages(pool, sources: list[UUID]) -> list[dict[str, Any]]:
    """As mensagens do turno de uma memória `conversa`, da pergunta à resposta final."""
    rows = [await conversations.get_message(pool, message_id) for message_id in sources]
    question = next((row for row in rows if row and row["role"] == "user"), None)
    final = next((row for row in rows if row and row["role"] == "assistant"), None)
    if not question or not final:
        return []
    path = await conversations.message_path(pool, final["id"])
    start = next((index for index, row in enumerate(path) if row["id"] == question["id"]), 0)

    messages = []
    for row in path[start:]:
        payload = row["payload"] or {}
        if row["role"] == "tool":
            messages.append({"role": "tool", "name": payload.get("name"), "content": _preview(row["content"], TOOL_OUTPUT_CHARS)})
        elif row["content"]:
            messages.append({"role": row["role"], "content": row["content"]})
    return messages


@tool(
    "ver_memoria",
    description=(
        "Mostra o conteúdo completo de uma memória encontrada por buscar_memorias; em "
        "trechos de conversa, inclui as mensagens originais."
    ),
    args_schema=MemoryIdInput,
)
async def view_memory(memory_id: UUID, runtime: ToolRuntime) -> dict[str, Any]:
    context = require_context(runtime)
    row = await memories.get_memory(context.pool, context.user_id, memory_id)
    if row is None:
        raise ToolException("Memória não encontrada.")

    status = "esquecida" if row["is_forgotten"] else "substituída" if row["superseded_by_id"] else "ativa"
    output: dict[str, Any] = {
        "memory_id": str(row["id"]),
        "category": row["category"],
        "date": row["created_at"].date().isoformat(),
        "status": status,
        "content": row["content"],
    }
    if row["category"] == "conversa":
        output["messages"] = await _turn_messages(context.pool, row["sources"])
    return output


@tool(
    "esquecer_memoria",
    description=(
        "Apaga uma memória errada ou que o usuário pediu para esquecer. Se o fato apenas "
        "mudou, use guardar_memoria."
    ),
    args_schema=MemoryIdInput,
)
async def forget_memory(memory_id: UUID, runtime: ToolRuntime) -> dict[str, Any]:
    context = require_context(runtime)
    row = await memories.forget(context.pool, context.user_id, memory_id)
    if row is None:
        raise ToolException("Memória não encontrada, ou já esquecida.")
    return {"memory_id": str(row["id"]), "category": row["category"], "forgotten": row["content"]}


TOOLS: list[BaseTool] = [
    obj
    for _, obj in inspect.getmembers(sys.modules[__name__], lambda o: isinstance(o, BaseTool))
]
# A ToolException volta ao modelo como resposta da ferramenta, marcada como erro.
for _tool in TOOLS:
    _tool.handle_tool_error = True
