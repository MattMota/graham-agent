from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from src.agent.config.settings import SETTINGS, chat_model

__all__ = ["SETTINGS", "bind_model"]


def bind_model(tools: list[BaseTool]) -> Runnable:
    """O modelo de chat com as ferramentas do agente.

    As ferramentas do MCP só são conhecidas na subida, ao listar o servidor;
    por isso a ligação acontece ao compilar o grafo, e não na importação.
    """
    model: BaseChatModel = chat_model()
    return model.bind_tools(tools=tools)
