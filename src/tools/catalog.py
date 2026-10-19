"""O catálogo das ferramentas do Graham: o que o servidor MCP publica.

Cada entrada liga um nome e uma descrição (o que o agente lê para decidir
chamá-la) ao modelo que valida os argumentos e à função que a executa. O
servidor MCP registra a partir daqui; o Graham usa os mesmos modelos nos
cartões de confirmação.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from src.tools import analysis, market, portfolio
from src.tools.context import ToolContext
from src.tools.schemas.analysis import AgendaInput, IncomeInput, PerformanceInput
from src.tools.schemas.market import (
    CompanySearchInput,
    IndustrySearchInput,
    TickerInput,
    TickerNewsInput,
    TopicNewsInput,
)
from src.tools.schemas.portfolio import (
    PortfolioViewInput,
    TradeInput,
    WatchInput,
    WatchRemoveInput,
    WatchViewInput,
)

# Escopos de um token de acesso. Toda chave lê; gravar exige a permissão de
# escrita, marcada quando a chave é criada.
READ = "graham:leitura"
WRITE = "graham:escrita"

Run = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    # Recebe o contexto e os argumentos já validados.
    run: Run
    scope: str
    # A função devolve (conteúdo, gráfico): o conteúdo vai ao agente; o
    # gráfico, só à interface, sem gastar tokens.
    chart: bool = False

    @property
    def writes(self) -> bool:
        return self.scope == WRITE


def _market(function: Callable[..., dict[str, Any]]) -> Run:
    """Os dados de mercado não dependem do usuário e usam o yfinance, que é
    síncrono: rodam numa thread, fora do event loop."""

    async def run(context: ToolContext, **arguments: Any) -> dict[str, Any]:
        return await asyncio.to_thread(function, **arguments)

    return run


CATALOG: list[ToolSpec] = [
    ToolSpec(
        name="cotacao_atual_acao",
        description=(
            "Retorna a cotação atual e os indicadores rápidos de uma ação a partir do seu ticker: "
            "nome da empresa, preço, variação do dia, abertura, máxima e mínima, volume, "
            "valor de mercado, máxima e mínima de 52 semanas e médias móveis. "
            "Use quando o usuário perguntar quanto vale uma ação ou como ela está se comportando hoje."
        ),
        input_model=TickerInput,
        run=_market(market.get_current_stock_price),
        scope=READ,
    ),
    ToolSpec(
        name="noticias_acao",
        description=(
            "Retorna as últimas notícias publicadas sobre uma ação, com título, resumo, "
            "data de publicação e link. Use quando o usuário quiser saber o que está sendo "
            "noticiado sobre uma empresa ou o que explica um movimento recente do papel."
        ),
        input_model=TickerNewsInput,
        run=_market(market.get_ticker_news),
        scope=READ,
    ),
    ToolSpec(
        name="noticias_tema",
        description=(
            "Busca notícias recentes sobre um tema em fontes brasileiras: política econômica, "
            "eleições, privatizações, regulação, juros, um setor inteiro. Use quando o assunto não "
            "for só uma empresa, ou quando as notícias da ação não explicarem um movimento do papel: "
            "busque o tema que pode estar por trás dele (a BBAS3 caiu por notícias eleitorais sobre "
            "privatizar o Banco do Brasil, por exemplo)."
        ),
        input_model=TopicNewsInput,
        run=_market(market.search_topic_news),
        scope=READ,
    ),
    ToolSpec(
        name="buscar_ticker_por_empresa",
        description=(
            "Busca os tickers correspondentes ao nome de uma empresa, retornando código, nome, "
            "bolsa, setor e indústria de cada resultado. Use quando o usuário citar a empresa pelo "
            "nome ('Banco do Brasil', 'Petrobras') e for preciso descobrir o ticker antes de "
            "consultar cotação ou notícias."
        ),
        input_model=CompanySearchInput,
        run=_market(market.find_ticker_by_company),
        scope=READ,
    ),
    ToolSpec(
        name="buscar_tickers_por_industria",
        description=(
            "Lista as principais empresas de uma indústria (subsetor) da classificação da Yahoo Finance, "
            "com ticker, nome, recomendação dos analistas e peso dentro da indústria. "
            "Exemplos de indústria: 'Banks - Regional', 'Software - Application', 'Oil & Gas E&P'. "
            "Aceita variações de escrita do nome. Use o parâmetro 'region' para filtrar por país "
            "(ex.: 'BR' para empresas brasileiras). Use para comparar concorrentes ou encontrar "
            "empresas de um mesmo segmento."
        ),
        input_model=IndustrySearchInput,
        run=_market(market.find_tickers_by_industry),
        scope=READ,
    ),
    ToolSpec(
        name="proventos",
        description=(
            "Mostra os proventos (dividendos, JCP, rendimentos de FIIs) de um ativo: pagamentos "
            "na janela pedida, total dos últimos 12 meses, dividend yield e a próxima data ex; se "
            "o usuário tem o ativo, também quanto ele recebeu. Sem ticker, calcula quanto a "
            "carteira do usuário recebeu, pela quantidade que ele tinha em cada data ex."
        ),
        input_model=IncomeInput,
        run=analysis.income,
        scope=READ,
    ),
    ToolSpec(
        name="desempenho",
        description=(
            "Compara o desempenho de até 4 ativos num período ou desde uma data (como a da "
            "compra): retorno com e sem proventos, retorno anualizado, volatilidade, maior queda, "
            "máxima e mínima, contra o Ibovespa ou o S&P 500. A interface mostra um gráfico. Use "
            "quando o usuário perguntar como um ativo evoluiu ou se foi melhor que outro."
        ),
        input_model=PerformanceInput,
        run=analysis.performance,
        scope=READ,
        chart=True,
    ),
    ToolSpec(
        name="agenda_eventos",
        description=(
            "Lista, em ordem de data, os próximos eventos de ativos: divulgação de resultados, "
            "datas ex e datas de pagamento de proventos. Sem tickers, cobre a carteira (posições "
            "em aberto, com a quantidade) e a watchlist do usuário. Use quando o usuário "
            "perguntar o que vem pela frente nos ativos dele, quando sai o balanço de uma empresa "
            "ou até quando comprar para receber um provento."
        ),
        input_model=AgendaInput,
        run=analysis.agenda,
        scope=READ,
    ),
    ToolSpec(
        name="ver_carteira",
        description=(
            "Mostra a carteira do usuário: quantidade, preço médio, total investido, cotação "
            "e valor atuais e resultado de cada ativo, com totais por moeda e o resultado das "
            "vendas já feitas. Use quando o usuário perguntar da carteira ou do desempenho dela."
        ),
        input_model=PortfolioViewInput,
        run=portfolio.view_portfolio,
        scope=READ,
    ),
    ToolSpec(
        name="ver_watchlist",
        description=(
            "Mostra a watchlist do usuário, com a cotação atual de cada ativo, a distância "
            "até o preço alvo e se o alvo já foi atingido."
        ),
        input_model=WatchViewInput,
        run=portfolio.view_watchlist,
        scope=READ,
    ),
    ToolSpec(
        name="registrar_compra",
        description=(
            "Registra uma compra na carteira do usuário; ele confirma ou corrige os valores "
            "antes de gravar. Informe sempre o preço unitário praticado: se a compra for de "
            "hoje e o usuário não disser o preço, consulte a cotação atual e use-a como "
            "sugestão; se for de outra data, pergunte o preço em vez de supor. O preço pode "
            "estar na moeda em que o usuário pagou: informe-a em `currency` (Bitcoin pago em "
            "reais é BTC-USD com currency 'BRL'), sem converter."
        ),
        input_model=TradeInput,
        run=portfolio.register_purchase,
        scope=WRITE,
    ),
    ToolSpec(
        name="registrar_venda",
        description=(
            "Registra uma venda na carteira do usuário, reduzindo a posição sem mudar o preço "
            "médio; ele confirma ou corrige os valores antes de gravar. Recusa vender mais do "
            "que a carteira tinha na data. O preço segue a mesma regra da compra."
        ),
        input_model=TradeInput,
        run=portfolio.register_sale,
        scope=WRITE,
    ),
    ToolSpec(
        name="adicionar_watchlist",
        description=(
            "Adiciona à watchlist do usuário um ativo a acompanhar, com a operação pretendida "
            "e o preço alvo. A quantidade é opcional e transforma o acompanhamento num plano, "
            "como 'comprar 100 a R$ 20'. O usuário confirma ou corrige os valores antes de gravar."
        ),
        input_model=WatchInput,
        run=portfolio.add_to_watchlist,
        scope=WRITE,
    ),
    ToolSpec(
        name="remover_watchlist",
        description=(
            "Remove uma entrada da watchlist do usuário, identificada pelo ativo e pela "
            "operação; o preço alvo só é preciso quando há mais de uma entrada assim. "
            "O usuário confirma antes da remoção."
        ),
        input_model=WatchRemoveInput,
        run=portfolio.remove_from_watchlist,
        scope=WRITE,
    ),
]

BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in CATALOG}

# O que grava dados: no Graham, o grafo pausa antes até o usuário confirmar.
WRITES = frozenset(spec.name for spec in CATALOG if spec.writes)
