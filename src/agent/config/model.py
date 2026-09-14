import os
import tomllib

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from src.agent.tools.definition import TOOLS

load_dotenv()

SETTINGS = tomllib.loads(
    (os.path.dirname(__file__) / "settings.toml")
    .read_text(encoding="utf-8")
)

LLM = (
    ChatOpenAI(
        base_url=os.getenv("MODEL_PROVIDER_BASE_URL"),
        api_key=os.getenv("MODEL_PROVIDER_API_KEY"),
        model=SETTINGS["llm"]["model"],
        temperature=SETTINGS["llm"]["temperature"],
        timeout=SETTINGS["llm"]["timeout"],
    )
    .bind_tools(
        tools=TOOLS,
    )
)
