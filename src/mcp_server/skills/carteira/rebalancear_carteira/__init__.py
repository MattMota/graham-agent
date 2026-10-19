from src.mcp_server.skills.skill import Argument, load

SKILL = load(
    __file__,
    arguments=(Argument("aporte", "Dinheiro novo a investir, em reais, como '5000'", required=False),),
    tools=("ver_enquadramento", "definir_alocacao", "sugerir_rebalanceamento", "registrar_compra", "registrar_venda"),
)
