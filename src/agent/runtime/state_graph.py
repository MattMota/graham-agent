from typing import TypedDict, Annotated, Literal

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver

from src.agent.config.model import LLM
from src.agent.instructions import SYSTEM_PROMPT
from src.agent.tools.definition import TOOLS


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

tool_node = ToolNode(
    tools=TOOLS,
)

async def call_model(state: AgentState) -> dict:
    response = await LLM.ainvoke([SYSTEM_PROMPT, *state["messages"]])
    # adiciona a resposta do modelo no estado (messages)
    return {"messages": [response]}


RE_ACT_GRAPH = (
    StateGraph(AgentState)

    # Nodes
    .add_node("agent", call_model) # Basic agent response
    .add_node("tools", tool_node) # Tool calling

    # Edges
    .add_edge(START, "agent") # Startup
    .add_conditional_edges("agent", tools_condition) # If the agent concludes a tool call is needed, go to the tool node
    .add_edge("tools", "agent") # After the tool is called, always go back to the agent node
    # .add_edge("agent", END) # If the agent doesn't want to call a tool, go to the end.
    # The above is redundant with `tools_condition`, which automatically moves to END if the agent concludes a tool call isn't needed.

    # Create the graph
    .compile(
        checkpointer=InMemorySaver() # Uses in-memory checkpointer to save graph state
    )
)