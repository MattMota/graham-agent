from src.mcp_server.skills.skill import load

SKILL = load(__file__, tools=("ver_carteira", "proventos", "ver_watchlist"))
