"""Todas as ferramentas do agente, reunidas de cada módulo."""

from src.agent.tools import analysis, definition, portfolio

TOOLS = [*definition.TOOLS, *portfolio.TOOLS, *analysis.TOOLS]

# Ferramentas que gravam dados: o grafo pausa antes delas até o usuário decidir.
APPROVAL_REQUIRED = portfolio.APPROVAL_REQUIRED
