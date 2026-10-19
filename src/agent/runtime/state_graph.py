"""O grafo do agente: o modelo, a pausa para confirmação e as ferramentas."""

import json
from datetime import date
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command, Send, interrupt
from pydantic import ValidationError

from src.agent.config.model import bind_model
from src.agent.instructions import SYSTEM_PROMPT
from src.agent.runtime.context import AgentContext
from src.agent.tools.registry import APPROVAL_REQUIRED
from src.tools.catalog import BY_NAME


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _with_edits(message: ToolMessage, edits: dict[str, Any]) -> ToolMessage:
    """Acrescenta ao resultado de uma gravação o que o usuário corrigiu no cartão.

    Sem isso, o modelo vê um valor gravado diferente do que o usuário disse na
    conversa e conclui que errou. O resultado fica no histórico, então vale
    também para os turnos seguintes.
    """
    if message.status == "error":
        return message
    try:
        output = json.loads(message.content)
    except (TypeError, ValueError):
        return message
    if not isinstance(output, dict):
        return message
    output["user_edits"] = edits
    output["note"] = (
        "O usuário corrigiu estes valores no cartão de confirmação antes de gravar; "
        "eles valem mais do que o que foi dito na conversa."
    )
    return message.model_copy(update={"content": json.dumps(output, ensure_ascii=False)})


def tools_node(tools: list[BaseTool]):
    node = ToolNode(
        tools=tools,
        # Sem isso, só os erros de validação dos argumentos chegariam ao modelo;
        # qualquer outra exceção de uma ferramenta (um ticker que não existe,
        # por exemplo) derrubaria o turno.
        handle_tool_errors=True,
    )

    async def run_tools(task: dict[str, Any], config: RunnableConfig) -> Any:
        output = await node.ainvoke(task, config)
        # As correções vão no estado enviado com cada chamada aprovada; a
        # ferramenta, atrás do MCP, nunca as vê.
        edits = (task.get("state") or {}).get("approval_edits") if isinstance(task, dict) else None
        if edits and isinstance(output, dict):
            output["messages"] = [
                _with_edits(message, edits) if isinstance(message, ToolMessage) else message
                for message in output["messages"]
            ]
        return output

    return run_tools


async def _respond(
    state: AgentState, runtime: Runtime[AgentContext], model: Runnable, sections: tuple[str, ...]
) -> dict:
    # As convenções das ferramentas e o catálogo de skills vêm da referência do
    # próprio servidor MCP: o prompt e o servidor não têm como divergir.
    parts = [SYSTEM_PROMPT.content, *sections]
    # O modelo não tem relógio: sem a data de hoje, não saberia preencher a
    # data de uma operação feita "hoje".
    parts.append(f"Hoje é {date.today():%Y-%m-%d}.")
    # O perfil e as preferências do usuário vão em toda chamada, para as
    # respostas os levarem em conta mesmo quando o modelo não pensa em buscá-los.
    profile = getattr(runtime.context, "profile", ())
    if profile:
        facts = "\n".join(f"- {fact}" for fact in profile)
        parts.append(f"# O que você sabe sobre o usuário\n\n{facts}")
    response = await model.ainvoke([SystemMessage("\n\n".join(parts)), *state["messages"]])
    return {"messages": [response]}


def route_after_model(state: AgentState) -> str:
    """Encerra o turno, roda as ferramentas ou, antes, pede a confirmação do usuário."""
    message = state["messages"][-1]
    if not isinstance(message, AIMessage) or not message.tool_calls:
        return END
    if any(call["name"] in APPROVAL_REQUIRED for call in message.tool_calls):
        return "approval"
    return "tools"


def _to_tools(call: dict[str, Any], state: AgentState, edits: dict[str, Any] | None = None) -> Send:
    # Uma tarefa por chamada, como faz o `create_agent`: só rodam as chamadas
    # listadas aqui, então uma operação cancelada nunca chega à ferramenta. As
    # correções vão no estado que a ferramenta vê por `ToolRuntime.state`.
    if edits:
        state = {**state, "approval_edits": edits}
    return Send("tools", {"__type": "tool_call_with_context", "tool_call": call, "state": state})


def _user_edits(name: str, proposed: dict[str, Any], approved: dict[str, Any]) -> dict[str, Any]:
    """Os campos que o usuário mudou no cartão, com os dois valores.

    A proposta passa antes pelo mesmo schema, para um ticker que o modelo
    escreveu em minúsculas não contar como correção.
    """
    try:
        proposed = BY_NAME[name].input_model.model_validate(proposed).model_dump(mode="json")
    except ValidationError:
        pass
    return {
        key: {"proposed": proposed.get(key), "approved": value}
        for key, value in approved.items()
        if proposed.get(key) != value
    }


async def request_approval(state: AgentState, runtime: Runtime[AgentContext]) -> Command:
    """Pausa o grafo até o usuário aprovar, corrigir ou cancelar cada gravação.

    Ao retomar, o LangGraph roda este nó de novo do começo, com o `interrupt`
    devolvendo as decisões. Por isso a pausa fica aqui, num nó sem efeitos
    colaterais, e não dentro das ferramentas: repeti-lo não repete nada.
    """
    message: AIMessage = state["messages"][-1]

    # O REPL não tem contexto nem como responder; as ferramentas avisam sozinhas.
    if runtime.context is None:
        return Command(goto=[_to_tools(call, state) for call in message.tool_calls])

    pending = [call for call in message.tool_calls if call["name"] in APPROVAL_REQUIRED]
    decisions: dict[str, dict[str, Any]] = interrupt([
        {"tool_call_id": call["id"], "name": call["name"], "args": call["args"]}
        for call in pending
    ])

    calls, approved, cancelled = [], [], []
    edits: dict[str, dict[str, Any]] = {}
    for call in message.tool_calls:
        if call["name"] in APPROVAL_REQUIRED:
            decision = decisions.get(call["id"]) or {}
            if not decision.get("approved"):
                cancelled.append(ToolMessage(
                    "O usuário cancelou esta operação; nada foi gravado.",
                    tool_call_id=call["id"],
                    name=call["name"],
                    status="error",
                ))
                calls.append(call)
                continue
            # O usuário pode ter corrigido os valores antes de aprovar.
            final = decision.get("args") or call["args"]
            edits[call["id"]] = _user_edits(call["name"], call["args"], final)
            call = {**call, "args": final}
        calls.append(call)
        approved.append(call)

    # O mesmo id faz o `add_messages` substituir a mensagem do modelo em vez de
    # acrescentar: o histórico fica com os valores que o usuário aprovou.
    revised = message.model_copy(update={"tool_calls": calls})
    update = {"messages": [revised, *cancelled]}

    if not approved:
        return Command(update=update, goto="agent")
    return Command(
        update=update,
        goto=[_to_tools(call, state, edits.get(call["id"])) for call in approved],
    )


def agent_node(model: Runnable, sections: tuple[str, ...]):
    async def call_model(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        return await _respond(state, runtime, model, sections)

    return call_model


def compile_graph(
    checkpointer: BaseCheckpointSaver, tools: list[BaseTool], sections: tuple[str, ...] = ()
) -> CompiledStateGraph:
    """Compila o grafo com o checkpointer de quem vai executá-lo e as ferramentas.

    O servidor usa o Postgres; o REPL, a memória do processo. A pausa para
    aprovação depende do checkpointer: é nele que o grafo espera a resposta.
    As ferramentas vêm do servidor MCP, listado na subida, e da memória local;
    `sections` são as partes do prompt lidas do mesmo servidor (convenções e
    skills).
    """
    builder = (
        StateGraph(AgentState, context_schema=AgentContext)
        # O modelo responde ou pede ferramentas.
        .add_node("agent", agent_node(bind_model(tools), sections))
        # As gravações esperam aqui pela confirmação do usuário.
        .add_node("approval", request_approval, destinations=("tools", "agent"))
        .add_node("tools", tools_node(tools))
        .add_edge(START, "agent")
        .add_conditional_edges("agent", route_after_model, ["approval", "tools", END])
        # Depois das ferramentas, o modelo sempre lê o resultado.
        .add_edge("tools", "agent")
    )
    return builder.compile(checkpointer=checkpointer)
