"""O agente de verdade para os evals: o modelo do `.env`, com as mesmas
ferramentas e o mesmo prompt do servidor, sem rodar nenhuma ferramenta."""

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values


@pytest.fixture(scope="session")
def agent():
    # O `tests/conftest.py` trocou a chave por uma falsa; aqui volta a real.
    real = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    if not real.get("MODEL_PROVIDER_API_KEY"):
        pytest.skip("Sem MODEL_PROVIDER_API_KEY no .env, não há modelo para avaliar.")
    os.environ["MODEL_PROVIDER_BASE_URL"] = real.get("MODEL_PROVIDER_BASE_URL") or ""
    os.environ["MODEL_PROVIDER_API_KEY"] = real["MODEL_PROVIDER_API_KEY"]

    from src.agent.config.model import bind_model
    from src.agent.tools.registry import load_agent

    setup = asyncio.run(load_agent())
    return bind_model(setup.tools), setup.sections
