"""O modelo de verdade escolhe a ferramenta certa? Não determinístico, por isso eval.

Cada pergunta vai ao modelo configurado no `.env` algumas vezes, com o mesmo
prompt e as mesmas ferramentas do servidor, e passa quando a maioria das
respostas começa por uma ferramenta aceitável. Nenhuma ferramenta roda: só a
primeira decisão do modelo é avaliada. Custa tokens; rode com:

    uv run pytest -m eval
"""

import asyncio

import pytest
from langchain_core.messages import HumanMessage

from tests.evals.agent import respond

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
    ("Quero que o IVVB11.SA conte como exterior na minha alocação, não como ETF.", {"definir_classe_ativo", "ler_skill"}),
    ("Oi, tudo bem?", {None}),
]


async def first_tool(agent, question):
    response = await respond(agent, [HumanMessage(question)])
    return response.tool_calls[0]["name"] if response.tool_calls else None


@pytest.mark.parametrize(("question", "accepted"), CASES, ids=[question for question, _ in CASES])
async def test_primeira_ferramenta(agent, question, accepted):
    chosen = await asyncio.gather(*(first_tool(agent, question) for _ in range(TRIES)))

    hits = sum(name in accepted for name in chosen)
    assert hits >= NEEDED, f"escolheu {chosen}, aceitas {sorted(map(str, accepted))}"
