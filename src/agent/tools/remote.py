"""As ferramentas do servidor MCP, vistas pelo agente como ferramentas LangChain.

As definições (nome, descrição, esquema de entrada) vêm do próprio servidor, em
processo, na subida: nesse momento o HTTP ainda não atende. As chamadas vão
pelo protocolo, com o token do usuário do turno, numa conexão aberta pelo
servidor web no início do turno e fechada no fim (`turn_connection`).

Sem conexão (o REPL), a chamada vai ao servidor em processo, sem usuário: as
ferramentas de mercado funcionam, e as de carteira avisam que precisam de uma
conta.
"""

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from langgraph.runtime import get_runtime
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import CallToolResult, Tool
from psycopg_pool import AsyncConnectionPool

from src.agent.runtime.context import AgentContext
from src.mcp_server import resources
from src.mcp_server import server as mcp_server
from src.storage import tokens
from src.tools.catalog import READ, WRITE

logger = logging.getLogger("uvicorn.error")

# O token interno dura mais que qualquer turno; é apagado ao fim dele, e o que
# sobrar de um turno que caiu vence sozinho.
TURN_TOKEN_TTL = timedelta(hours=1)

# O SDK prefixa as falhas com o nome da ferramenta, em inglês; o modelo só
# precisa da explicação.
_ERROR_PREFIX = re.compile(r"^Error executing tool \S+: ")


def internal_url() -> str:
    """Onde o Graham alcança o próprio MCP; por padrão, o endereço público."""
    return os.getenv("MCP_INTERNAL_URL", f"{mcp_server.public_url()}{mcp_server.PATH}")


@asynccontextmanager
async def turn_connection(pool: AsyncConnectionPool, user_id: UUID) -> AsyncIterator[Client]:
    """Uma conexão MCP em nome do usuário, para um turno.

    O Graham usa um token interno, com leitura e escrita: as operações que
    gravam já passaram pelo cartão de confirmação antes de chegar aqui. O
    cookie da sessão nunca vai ao MCP.

    A conexão vive numa tarefa própria, que a abre e a fecha: o turno é um
    gerador que entrega eventos entre um passo e outro, e os escopos do anyio
    do cliente não podem ficar abertos através desses `yield`. As ferramentas
    chamam o cliente das suas próprias tarefas, como já fariam de qualquer jeito.
    """
    token, _ = await tokens.issue(pool, user_id, "interno", [READ, WRITE], ttl=TURN_TOKEN_TTL)
    ready: asyncio.Future[Client] = asyncio.get_running_loop().create_future()
    done = asyncio.Event()

    async def hold() -> None:
        try:
            http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
            async with Client(streamable_http_client(internal_url(), http_client=http)) as client:
                ready.set_result(client)
                await done.wait()
        except Exception as error:  # noqa: BLE001 - quem espera a conexão recebe o erro
            if not ready.done():
                ready.set_exception(error)
            else:
                logger.warning("Conexão MCP do turno encerrada com erro", exc_info=True)

    holder = asyncio.create_task(hold())
    try:
        yield await ready
    finally:
        done.set()
        await holder
        await tokens.discard(pool, token)


def _text(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if block.type == "text")


def _proxy(definition: Tool) -> BaseTool:
    name = definition.name

    async def call(**arguments: Any) -> tuple[str, Any]:
        context = get_runtime(AgentContext).context
        connection = context.mcp if isinstance(context, AgentContext) else None
        if connection is not None:
            result = await connection.call_tool(name, arguments)
        else:
            async with Client(mcp_server.server) as local:
                result = await local.call_tool(name, arguments)

        text = _text(result)
        if result.is_error:
            raise ToolException(_ERROR_PREFIX.sub("", text))
        # O gráfico do desempenho: vai à interface como artefato, não ao modelo.
        chart = (result.structured_content or {}).get("chart")
        return text, chart

    return StructuredTool(
        name=name,
        description=definition.description or "",
        args_schema=definition.input_schema,
        coroutine=call,
        response_format="content_and_artifact",
        # A falha volta ao modelo como resposta da ferramenta, marcada como erro.
        handle_tool_error=True,
    )


async def load_conventions() -> str:
    """As convenções das ferramentas, lidas do próprio MCP, para o prompt do Graham.

    Fica de fora a seção de escrita: ela pede a um agente externo que confirme
    com o usuário antes de gravar, e no Graham quem confirma é o cartão.
    """
    async with Client(mcp_server.server) as local:
        text = (await local.read_resource(resources.CONVENTIONS)).contents[0].text
    sections = re.split(r"(?m)^(?=## )", text)[1:]
    return "".join(section for section in sections if not section.startswith("## Escrita")).strip()


async def load() -> list[BaseTool]:
    """As ferramentas que o servidor MCP publica, como ferramentas LangChain."""
    async with Client(mcp_server.server) as local:
        definitions = (await local.list_tools()).tools
    return [_proxy(definition) for definition in definitions]
