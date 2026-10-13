"""Tudo o que o agente carrega na subida: as ferramentas (as do servidor MCP e
as locais) e as seções do prompt que vêm do MCP (convenções e skills)."""

from dataclasses import dataclass

from langchain_core.tools import BaseTool

from src.agent.tools import memory, remote, skills
from src.tools.catalog import WRITES

# Ferramentas que gravam dados: o grafo pausa antes delas até o usuário decidir.
APPROVAL_REQUIRED = WRITES


@dataclass(frozen=True)
class AgentSetup:
    tools: list[BaseTool]
    # Seções acrescentadas ao prompt de sistema, cada uma com o seu título.
    sections: tuple[str, ...]


async def load_agent() -> AgentSetup:
    """As ferramentas do MCP (mercado, análise, carteira, watchlist), a memória,
    que é do próprio Graham e não sai dele, e a leitura das skills do MCP."""
    catalog = await skills.load_catalog()
    tools = [*await remote.load(), *memory.TOOLS, skills.build_tool(catalog)]

    sections = []
    if conventions := await remote.load_conventions():
        sections.append("# Convenções das ferramentas\n\n" + conventions)
    if catalog_text := skills.catalog_prompt(catalog):
        sections.append("# Skills\n\n" + catalog_text)
    return AgentSetup(tools, tuple(sections))
