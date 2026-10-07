"""Configurações do agente e o cliente do modelo, sem depender das ferramentas.

Fica à parte do `model.py`, que vincula as ferramentas ao modelo: quem precisa
do modelo puro (o processamento de memória, por exemplo) importa daqui sem
criar um import circular com o registro de ferramentas.
"""

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

SETTINGS = tomllib.loads(
    (Path(__file__).parent / "settings.toml").read_text(encoding="utf-8")
)


def chat_model(**overrides) -> ChatOpenAI:
    """O modelo de chat configurado, sem ferramentas vinculadas."""
    options = {
        "model": SETTINGS["llm"]["model"],
        "temperature": SETTINGS["llm"]["temperature"],
        "timeout": SETTINGS["llm"]["timeout"],
        **overrides,
    }
    return ChatOpenAI(
        base_url=os.getenv("MODEL_PROVIDER_BASE_URL"),
        api_key=os.getenv("MODEL_PROVIDER_API_KEY"),
        **options,
    )
