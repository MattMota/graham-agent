from src.mcp_server.skills.skill import Argument, load

SKILL = load(
    __file__,
    arguments=(Argument("operacao", "O que registrar, como 'comprei 100 PETR4 a 38,50 ontem'", required=True),),
    tools=("buscar_ticker_por_empresa", "cotacao_atual_acao", "registrar_compra", "registrar_venda"),
)
