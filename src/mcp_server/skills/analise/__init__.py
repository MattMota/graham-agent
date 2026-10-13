"""Skills de análise de ativos."""

from src.mcp_server.skills.analise import analisar_ativo, explicar_movimento

SKILLS = [analisar_ativo.SKILL, explicar_movimento.SKILL]
