from src.mcp_server.skills.skill import Argument, load

SKILL = load(
    __file__,
    arguments=(
        Argument("ticker", "O ativo, como PETR4.SA", required=True),
        Argument("periodo", "Janela do movimento: 1mo, 3mo, 6mo, ytd ou 1y (padrão 1mo)"),
    ),
    tools=("desempenho", "noticias_acao", "noticias_tema"),
)
