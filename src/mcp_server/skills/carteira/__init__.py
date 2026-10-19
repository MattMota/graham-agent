"""Skills sobre a carteira e as operações do usuário."""

from src.mcp_server.skills.carteira import rebalancear_carteira, registrar_operacao, revisar_carteira

SKILLS = [revisar_carteira.SKILL, registrar_operacao.SKILL, rebalancear_carteira.SKILL]
