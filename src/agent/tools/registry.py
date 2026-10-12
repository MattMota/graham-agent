"""Todas as ferramentas do agente: as do servidor MCP e as locais."""

from langchain_core.tools import BaseTool

from src.agent.tools import memory, remote
from src.tools.catalog import WRITES

# Ferramentas que gravam dados: o grafo pausa antes delas até o usuário decidir.
APPROVAL_REQUIRED = WRITES


async def load_tools() -> list[BaseTool]:
    """As do MCP (mercado, análise, carteira, watchlist) e a memória, que é do
    próprio Graham e não sai dele."""
    return [*await remote.load(), *memory.TOOLS]
