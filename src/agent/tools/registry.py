"""Todas as ferramentas do agente, reunidas de cada módulo."""

from src.agent.tools import analysis, definition, memory, portfolio

TOOLS = [*definition.TOOLS, *portfolio.TOOLS, *analysis.TOOLS, *memory.TOOLS]

# Ferramentas que gravam dados: o grafo pausa antes delas até o usuário decidir.
APPROVAL_REQUIRED = portfolio.APPROVAL_REQUIRED
