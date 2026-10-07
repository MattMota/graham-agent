from src.agent.config.settings import SETTINGS, chat_model
from src.agent.tools.registry import TOOLS

__all__ = ["LLM", "SETTINGS"]

LLM = chat_model().bind_tools(tools=TOOLS)
