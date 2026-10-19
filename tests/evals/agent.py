"""A chamada ao modelo de verdade que os evals compartilham."""

from types import SimpleNamespace


async def respond(agent, messages):
    """A próxima resposta do modelo para o histórico dado, sem usuário."""
    from src.agent.runtime.state_graph import _respond

    model, sections = agent
    output = await _respond({"messages": messages}, SimpleNamespace(context=None), model, sections)
    return output["messages"][0]
