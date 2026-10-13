from src.mcp_server.skills.skill import Argument, load

SKILL = load(
    __file__,
    arguments=(Argument("ticker", "O ativo, como PETR4.SA", required=True),),
    tools=("buscar_ticker_por_empresa", "cotacao_atual_acao", "desempenho", "proventos", "noticias_acao"),
)
