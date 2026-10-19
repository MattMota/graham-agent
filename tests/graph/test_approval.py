"""O grafo do agente com um modelo roteirizado: consultas, confirmação e cancelamento.

As ferramentas aqui são locais e só registram o que receberam: o que se testa é
a ordem dos nós, o que chega às ferramentas e o que volta ao modelo.
"""

import json
from uuid import uuid4

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.agent.runtime import state_graph
from src.agent.runtime.context import AgentContext
from src.tools.schemas.market import TickerInput
from src.tools.schemas.portfolio import TradeInput
from tests.fakes import ScriptedModel, calls, says

PURCHASE = {"ticker_name": "PETR4.SA", "quantity": 100, "unit_price": 30.0, "traded_on": "2026-10-01"}


@pytest.fixture
def model(monkeypatch):
    model = ScriptedModel()
    monkeypatch.setattr(state_graph, "bind_model", lambda tools: model)
    return model


@pytest.fixture
def executed():
    """O que cada ferramenta recebeu, na ordem."""
    return []


@pytest.fixture
def graph(model, executed):
    async def quote(**args):
        executed.append(("cotacao_atual_acao", args))
        return json.dumps({"ticker_name": args["ticker_name"], "price": 31.2})

    async def purchase(**args):
        executed.append(("registrar_compra", args))
        return json.dumps({"operation": "compra", **args}, default=str)

    tools = [
        StructuredTool.from_function(coroutine=quote, name="cotacao_atual_acao", description="Cotação.", args_schema=TickerInput),
        StructuredTool.from_function(coroutine=purchase, name="registrar_compra", description="Compra.", args_schema=TradeInput),
    ]
    return state_graph.compile_graph(InMemorySaver(), tools)


def run(graph, payload, *, context=True):
    config = {"configurable": {"thread_id": str(uuid4())}}
    ctx = AgentContext(user_id=uuid4(), pool=None) if context else None

    async def go(value=payload):
        return await graph.ainvoke(value, config, context=ctx)

    return go


def tool_messages(state):
    return [message for message in state["messages"] if isinstance(message, ToolMessage)]


async def test_consulta_roda_direto_e_o_resultado_volta_ao_modelo(graph, model, executed):
    model.script = [calls(("cotacao_atual_acao", {"ticker_name": "petr4.sa"})), says("A PETR4 vale R$ 31,20.")]

    state = await run(graph, {"messages": [("user", "Quanto vale a PETR4?")]})()

    assert "__interrupt__" not in state
    assert executed == [("cotacao_atual_acao", {"ticker_name": "PETR4.SA"})]
    assert state["messages"][-1].content == "A PETR4 vale R$ 31,20."
    # A segunda chamada ao modelo já leva o resultado da ferramenta.
    assert isinstance(model.received[1][-1], ToolMessage)


async def test_operacao_pausa_antes_de_gravar(graph, model, executed):
    model.script = [calls(("registrar_compra", PURCHASE))]

    state = await run(graph, {"messages": [("user", "Comprei 100 PETR4 a 30.")]})()

    [pause] = state["__interrupt__"]
    assert pause.value == [{"tool_call_id": "call_registrar_compra_0", "name": "registrar_compra", "args": PURCHASE}]
    assert executed == []


async def test_valores_corrigidos_no_cartao_chegam_a_ferramenta_e_ao_modelo(graph, model, executed):
    model.script = [calls(("registrar_compra", PURCHASE)), says("Registrei a compra.")]
    go = run(graph, {"messages": [("user", "Comprei 100 PETR4 a 30.")]})
    await go()

    approved = {**PURCHASE, "unit_price": 29.5}
    state = await go(Command(resume={"call_registrar_compra_0": {"approved": True, "args": approved}}))

    assert executed == [("registrar_compra", TradeInput.model_validate(approved).model_dump())]
    [result] = tool_messages(state)
    output = json.loads(result.content)
    assert output["user_edits"] == {"unit_price": {"proposed": 30.0, "approved": 29.5}}
    # O histórico guarda o valor aprovado, não o proposto.
    assert state["messages"][1].tool_calls[0]["args"]["unit_price"] == 29.5


async def test_operacao_cancelada_nao_roda_e_o_modelo_explica(graph, model, executed):
    model.script = [calls(("registrar_compra", PURCHASE)), says("Ok, não registrei.")]
    go = run(graph, {"messages": [("user", "Comprei 100 PETR4 a 30.")]})
    await go()

    state = await go(Command(resume={"call_registrar_compra_0": {"approved": False}}))

    assert executed == []
    [cancelled] = tool_messages(state)
    assert cancelled.status == "error" and "cancelou" in cancelled.content
    assert state["messages"][-1].content == "Ok, não registrei."


async def test_na_mesma_resposta_so_rodam_a_consulta_e_a_operacao_aprovada(graph, model, executed):
    second = {**PURCHASE, "ticker_name": "VALE3.SA"}
    model.script = [
        calls(("cotacao_atual_acao", {"ticker_name": "PETR4.SA"}), ("registrar_compra", PURCHASE), ("registrar_compra", second)),
        says("Feito."),
    ]
    go = run(graph, {"messages": [("user", "Veja a PETR4 e registre as compras.")]})
    await go()
    # A consulta também espera: a resposta do modelo pausa inteira.
    assert executed == []

    await go(Command(resume={
        "call_registrar_compra_1": {"approved": True},
        "call_registrar_compra_2": {"approved": False},
    }))

    assert sorted((name, args["ticker_name"]) for name, args in executed) == [
        ("cotacao_atual_acao", "PETR4.SA"), ("registrar_compra", "PETR4.SA"),
    ]


async def test_sem_contexto_o_repl_grava_sem_confirmar(graph, model, executed):
    model.script = [calls(("registrar_compra", PURCHASE)), says("Registrado.")]

    state = await run(graph, {"messages": [("user", "Comprei 100 PETR4 a 30.")]}, context=False)()

    assert "__interrupt__" not in state
    assert [name for name, _ in executed] == ["registrar_compra"]


async def test_perfil_do_usuario_e_a_data_de_hoje_vao_no_prompt(graph, model):
    model.script = [says("Olá.")]
    config = {"configurable": {"thread_id": str(uuid4())}}
    context = AgentContext(user_id=uuid4(), pool=None, profile=("Perfil conservador.",))

    await graph.ainvoke({"messages": [("user", "Oi")]}, config, context=context)

    system = model.received[0][0].content
    assert "- Perfil conservador." in system
    assert "Hoje é " in system
