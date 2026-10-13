from datetime import date
from typing import TypedDict, Annotated, Any

import json

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
    """Adds to a write's result what the user corrected on the confirmation card.

    Without it, the model sees a stored value different from what the user said
    in the conversation and concludes it made a mistake. The result stays in
    the history, so this holds for the following turns as well.
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
        # Without this, only argument validation errors reach the model; any
        # other exception raised by a tool (an unknown ticker, say) would abort
        # the turn.
        handle_tool_errors=True,
    )

    async def run_tools(task: dict[str, Any], config: RunnableConfig) -> Any:
        output = await node.ainvoke(task, config)
        # The edits ride along in the state sent with each approved call; the
        # tool itself, now behind MCP, never sees them.
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
    # The tools' conventions and the skills catalog come from the MCP server's
    # own reference, so the prompt and the server never drift apart.
    parts = [SYSTEM_PROMPT.content, *sections]
    # The model has no clock: without today's date it cannot fill in the date
    # of a trade made "hoje".
    parts.append(f"Hoje é {date.today():%Y-%m-%d}.")
    # The user's profile and preferences ride along in every call, so answers
    # take them into account even when the model does not think to search.
    profile = getattr(runtime.context, "profile", ())
    if profile:
        facts = "\n".join(f"- {fact}" for fact in profile)
        parts.append(f"# O que você sabe sobre o usuário\n\n{facts}")
    response = await model.ainvoke([SystemMessage("\n\n".join(parts)), *state["messages"]])
    # adiciona a resposta do modelo no estado (messages)
    return {"messages": [response]}


def route_after_model(state: AgentState) -> str:
    """Ends the turn, runs the tools, or first asks the user to approve them."""
    message = state["messages"][-1]
    if not isinstance(message, AIMessage) or not message.tool_calls:
        return END
    if any(call["name"] in APPROVAL_REQUIRED for call in message.tool_calls):
        return "approval"
    return "tools"


def _to_tools(call: dict[str, Any], state: AgentState, edits: dict[str, Any] | None = None) -> Send:
    # One task per tool call, as `create_agent` does: only the calls listed
    # here run, so a cancelled operation never reaches its tool. The edits ride
    # along in the state the tool sees through `ToolRuntime.state`.
    if edits:
        state = {**state, "approval_edits": edits}
    return Send("tools", {"__type": "tool_call_with_context", "tool_call": call, "state": state})


def _user_edits(name: str, proposed: dict[str, Any], approved: dict[str, Any]) -> dict[str, Any]:
    """The fields the user changed on the card, with both values.

    The proposal goes through the same schema first, so a ticker the model
    wrote in lower case does not count as an edit.
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
    """Pauses the graph until the user approves, edits or cancels each write.

    On resume LangGraph runs this node again from the top, with `interrupt`
    returning the decisions. That is why the pause lives here, in a node with no
    side effects, and not inside the tools: a re-run here repeats nothing.
    """
    message: AIMessage = state["messages"][-1]

    # The REPL has no context and no way to answer; the tools say so themselves.
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
            # The user may have corrected the values before approving.
            final = decision.get("args") or call["args"]
            edits[call["id"]] = _user_edits(call["name"], call["args"], final)
            call = {**call, "args": final}
        calls.append(call)
        approved.append(call)

    # Same id, so `add_messages` replaces the model's message instead of
    # appending: the history keeps the values the user actually approved.
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

        # Nodes
        .add_node("agent", agent_node(bind_model(tools), sections)) # Basic agent response
        .add_node("approval", request_approval, destinations=("tools", "agent")) # Human in the loop
        .add_node("tools", tools_node(tools)) # Tool calling

        # Edges
        .add_edge(START, "agent") # Startup
        .add_conditional_edges("agent", route_after_model, ["approval", "tools", END]) # Writes need approval first
        .add_edge("tools", "agent") # After the tool is called, always go back to the agent node
    )
    return builder.compile(checkpointer=checkpointer)
