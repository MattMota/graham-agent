from datetime import date
from typing import TypedDict, Annotated, Any

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import Command, Send, interrupt
from pydantic import ValidationError

from src.agent.config.model import LLM
from src.agent.instructions import SYSTEM_PROMPT
from src.agent.runtime.context import AgentContext
from src.agent.tools.registry import APPROVAL_REQUIRED, TOOLS


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

tool_node = ToolNode(
    tools=TOOLS,
    # Without this, only argument validation errors reach the model; any other
    # exception raised by a tool (an unknown ticker, say) would abort the turn.
    handle_tool_errors=True,
)

async def call_model(state: AgentState) -> dict:
    # The model has no clock: without today's date it cannot fill in the date
    # of a trade made "hoje".
    system = SystemMessage(f"{SYSTEM_PROMPT.content}\n\nHoje é {date.today():%Y-%m-%d}.")
    response = await LLM.ainvoke([system, *state["messages"]])
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


TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


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
        proposed = TOOLS_BY_NAME[name].args_schema.model_validate(proposed).model_dump(mode="json")
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


GRAPH_BUILDER = (
    StateGraph(AgentState, context_schema=AgentContext)

    # Nodes
    .add_node("agent", call_model) # Basic agent response
    .add_node("approval", request_approval, destinations=("tools", "agent")) # Human in the loop
    .add_node("tools", tool_node) # Tool calling

    # Edges
    .add_edge(START, "agent") # Startup
    .add_conditional_edges("agent", route_after_model, ["approval", "tools", END]) # Writes need approval first
    .add_edge("tools", "agent") # After the tool is called, always go back to the agent node
)


def compile_graph(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    """Compila o grafo com o checkpointer de quem vai executá-lo.

    O servidor usa o Postgres; o REPL, a memória do processo. A pausa para
    aprovação depende do checkpointer: é nele que o grafo espera a resposta.
    """
    return GRAPH_BUILDER.compile(checkpointer=checkpointer)
