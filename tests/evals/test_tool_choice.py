"""O modelo de verdade escolhe a ferramenta certa? Não determinístico, por isso eval.

Cada pergunta vai ao modelo configurado no `.env` algumas vezes, com o mesmo
prompt e as mesmas ferramentas do servidor, e passa quando a maioria das
respostas começa por uma ferramenta aceitável. Nenhuma ferramenta roda: só a
primeira decisão do modelo é avaliada. Custa tokens; rode com:

    uv run pytest -m eval
"""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values
from langchain_core.messages import HumanMessage

pytestmark = pytest.mark.eval

# Quantas vezes cada pergunta vai ao modelo, e quantas precisam acertar.
TRIES = 3
NEEDED = 2

CASES = [
    ("Quanto vale a PETR4.SA hoje?", {"cotacao_atual_acao"}),
    ("O que eu tenho na minha carteira?", {"ver_carteira"}),
    ("Quanto a minha carteira recebeu de proventos nos últimos 12 meses?", {"proventos"}),
    ("Quais eventos vêm por aí nos ativos da minha carteira?", {"agenda_eventos"}),
    ("Quando sai o próximo balanço da VALE3.SA?", {"agenda_eventos"}),
    # Ler antes a skill `registrar-operacao` também é o caminho certo.
    ("Comprei hoje 100 ITUB4.SA a R$ 35,00.", {"registrar_compra", "ler_skill"}),
    ("A BBAS3.SA caiu muito esta semana. Por quê?", {"ler_skill", "desempenho", "noticias_acao", "noticias_tema"}),
    ("Guarde que o meu perfil de investidor é conservador.", {"guardar_memoria"}),
    ("Minha carteira está enquadrada na minha alocação-alvo?", {"ver_enquadramento", "ler_skill"}),
    ("Tenho R$ 5.000 para aportar. Onde coloco para voltar ao meu alvo?", {"sugerir_rebalanceamento", "ver_enquadramento", "ler_skill"}),
    ("Quero 70% em ações brasileiras e 30% em fundos imobiliários.", {"definir_alocacao", "ler_skill"}),
    ("Oi, tudo bem?", {None}),
]


@pytest.fixture(scope="module")
def agent():
    real = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    if not real.get("MODEL_PROVIDER_API_KEY"):
        pytest.skip("Sem MODEL_PROVIDER_API_KEY no .env, não há modelo para avaliar.")
    os.environ["MODEL_PROVIDER_BASE_URL"] = real.get("MODEL_PROVIDER_BASE_URL") or ""
    os.environ["MODEL_PROVIDER_API_KEY"] = real["MODEL_PROVIDER_API_KEY"]

    from src.agent.config.model import bind_model
    from src.agent.tools.registry import load_agent

    setup = asyncio.run(load_agent())
    return bind_model(setup.tools), setup.sections


async def first_tool(model, sections, question):
    from src.agent.runtime.state_graph import _respond

    # Sem usuário: o mesmo prompt de sistema, sem o perfil.
    output = await _respond({"messages": [HumanMessage(question)]}, SimpleNamespace(context=None), model, sections)
    calls = output["messages"][0].tool_calls
    return calls[0]["name"] if calls else None


@pytest.mark.parametrize(("question", "accepted"), CASES, ids=[question for question, _ in CASES])
async def test_primeira_ferramenta(agent, question, accepted):
    model, sections = agent

    chosen = await asyncio.gather(*(first_tool(model, sections, question) for _ in range(TRIES)))

    hits = sum(name in accepted for name in chosen)
    assert hits >= NEEDED, f"escolheu {chosen}, aceitas {sorted(map(str, accepted))}"
