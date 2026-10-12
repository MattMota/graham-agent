"""Material de referência servido pelo MCP: o que um agente precisa saber para
usar bem as ferramentas, sem depender do que as descrições cabem em dizer.

Só referência, nada do usuário: a carteira e a watchlist já são servidas pelas
ferramentas, e um resource com dados pessoais tende a entrar inteiro no
contexto do agente cliente sem que ele peça.

Convenções e glossário são texto estável, escrito à mão. As fontes trazem os
prazos de cache das próprias constantes do código, e os catálogos vêm dos
mesmos dados que a validação usa: os dois não têm como divergir dela.
"""

from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from yfinance.const import SECTOR_INDUSTY_MAPPING

from src.tools import analysis, market
from src.tools.schemas.market import industry_key
from src.tools.schemas.portfolio import CURRENCIES

HERE = Path(__file__).parent

CONVENTIONS = "graham://convencoes"
GLOSSARY = "graham://glossario"
SOURCES = "graham://fontes"
INDUSTRIES = "graham://catalogo/industrias"
CURRENCY_LIST = "graham://catalogo/moedas"


def _markdown(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


def conventions() -> str:
    return _markdown("convencoes.md")


def _duration(seconds: int) -> str:
    hours = seconds // 3600
    return "1 hora" if hours == 1 else f"{hours} horas"


def sources() -> str:
    return f"""# Fontes e limites dos dados

De onde vem cada dado das ferramentas do Graham, e o que esperar dele.

## Fontes

- **Cotações, históricos, proventos, buscas de ticker e setores**: Yahoo Finance, pela biblioteca yfinance. As cotações da B3 chegam com atraso de cerca de 15 minutos; o horário de cada uma vem em `quoted_at`.
- **Notícias de uma ação** (`noticias_acao`): Yahoo Finance. O feed por ticker da Yahoo responde vazio desde 2026; nesse caso a ferramenta busca pelo nome da empresa, e as notícias vêm sem resumo.
- **Notícias de um tema** (`noticias_tema`): a busca do Google News em português, com fontes brasileiras. Vêm sem resumo, e os links passam por um redirecionamento do Google.
- **Câmbio**: Yahoo Finance, pelos pares de moedas (`USDBRL=X`), na cotação do momento.
- **Carteira e watchlist**: o que o usuário registrou no Graham. Operações de corretoras não chegam sozinhas.

## Cache

As respostas da Yahoo e do Google News ficam guardadas por um tempo, e duas consultas próximas devolvem o mesmo resultado:

| Dado | Por quanto tempo |
|---|---|
| Cotação | Sem cache: sempre consultada na hora |
| Notícias de uma ação ou de um tema | {_duration(market.NEWS_TTL)} |
| Histórico de preços (desempenho) | {_duration(analysis.HISTORY_TTL)} |
| Proventos | {_duration(analysis.INCOME_TTL)} |
| Busca de ticker e empresas por setor | {_duration(market.CATALOG_TTL)} |

Um resultado vazio não entra no cache: pode ser a fonte fora do ar, e a consulta seguinte tenta de novo.

## Limites

- Notícias sem resumo: não afirme além do que o título diz, e cite o veículo e a data.
- Os proventos são os registrados na Yahoo, que pode não ter todos.
- O desempenho compara no máximo 4 ativos, cada um na moeda da própria cotação.
"""


def industries() -> list[dict[str, Any]]:
    """Os subsetores aceitos por `buscar_tickers_por_industria`, com o setor de cada um."""
    return sorted(
        (
            {"key": industry_key(industry), "name": industry, "sector": sector}
            for sector, names in SECTOR_INDUSTY_MAPPING.items()
            for industry in names
        ),
        key=lambda item: (item["sector"], item["name"]),
    )


def currencies() -> list[dict[str, str]]:
    """As moedas aceitas para o preço de uma operação na carteira."""
    return [{"code": code, "name": name} for code, name in CURRENCIES.items()]


def register(server: MCPServer) -> None:
    server.resource(
        CONVENTIONS,
        name="convencoes",
        title="Convenções das ferramentas",
        description=(
            "Como as ferramentas leem os argumentos e escrevem os resultados: códigos de "
            "ativos, moedas, percentuais, datas, notas e erros. Leia antes de usá-las."
        ),
        mime_type="text/markdown",
    )(conventions)
    server.resource(
        GLOSSARY,
        name="glossario",
        title="Glossário",
        description=(
            "O sentido exato dos termos nos resultados (data ex, dividend yield, retorno com "
            "proventos, volatilidade, maior queda, preço médio) e como cada um é calculado."
        ),
        mime_type="text/markdown",
    )(lambda: _markdown("glossario.md"))
    server.resource(
        SOURCES,
        name="fontes",
        title="Fontes e limites dos dados",
        description="De onde vem cada dado, atrasos, por quanto tempo fica em cache e o que ele não cobre.",
        mime_type="text/markdown",
    )(sources)
    server.resource(
        INDUSTRIES,
        name="industrias",
        title="Subsetores da classificação Yahoo",
        description=(
            "Os 145 subsetores aceitos por `buscar_tickers_por_industria`, com a chave, o nome "
            "e o setor de cada um."
        ),
        mime_type="application/json",
    )(industries)
    server.resource(
        CURRENCY_LIST,
        name="moedas",
        title="Moedas da carteira",
        description="As moedas aceitas para o preço de uma operação na carteira, com o código ISO 4217.",
        mime_type="application/json",
    )(currencies)
