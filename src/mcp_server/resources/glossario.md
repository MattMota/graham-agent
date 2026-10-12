# Glossário do Graham

O sentido exato de cada termo nos resultados das ferramentas, como elas o calculam.

## Proventos

- **Provento**: dinheiro distribuído ao acionista ou cotista: dividendos, juros sobre capital próprio (JCP) e rendimentos de fundos imobiliários. Os valores são brutos, por ação ou cota, antes de impostos.
- **Data ex**: a partir dela o ativo é negociado sem o direito ao provento. Tem direito quem tinha o ativo no fim do pregão anterior à data ex. Os pagamentos são datados pela data ex.
- **Total em 12 meses** (`trailing_12m_total`): soma dos proventos com data ex nos últimos 12 meses.
- **Dividend yield** (`dividend_yield_12m`): total em 12 meses dividido pela cotação atual, em percentual.
- **Recebido pela carteira** (`received`): para cada pagamento, a quantidade que o usuário tinha no fim do pregão anterior à data ex vezes o valor por ação. Uma compra feita na própria data ex não entra.

## Desempenho

- **Retorno de preço** (`price_return_percent`): variação do preço de fechamento entre o primeiro e o último dia do período.
- **Retorno com proventos** (`total_return_percent`): variação do preço ajustado, que supõe os proventos reinvestidos no próprio ativo.
- **Retorno ao ano** (`annualized_return_percent`): o retorno com proventos levado a um ano, `(1 + retorno)^(365 / dias) - 1`. Só é calculado para períodos de um ano ou mais; abaixo disso, vem vazio.
- **Volatilidade** (`annualized_volatility_percent`): desvio padrão dos retornos diários logarítmicos, anualizado pelo número de pregões por ano da própria série (cerca de 252 na B3; criptomoedas negociam todos os dias).
- **Maior queda** (`max_drawdown_percent`): a pior queda do preço ajustado a partir de um pico anterior, com as datas do pico e do fundo (`max_drawdown_from`, `max_drawdown_to`).
- **Máxima e mínima** (`high`, `low`): o maior e o menor fechamento do período, com a data.

## Carteira

- **Preço médio** (`average_price`): média ponderada das compras, o critério da Receita e da B3. Uma venda reduz a quantidade sem mudar o preço médio.
- **Investido** (`invested`): quantidade atual vezes o preço médio.
- **Valor atual** (`current_value`): quantidade vezes a cotação atual, convertida para a moeda do preço quando as duas diferem.
- **Resultado** (`result`, `result_percent`): valor atual menos o investido, sobre a posição em aberto.
- **Resultado realizado** (`realized`): o ganho ou a perda das vendas já feitas, calculado contra o preço médio do momento de cada venda.

## Watchlist

- **Operação pretendida**: `compra` espera o preço cair até o alvo; `venda` e `short`, subir até ele.
- **Distância até o alvo** (`distance_percent`): quanto a cotação atual está acima (positivo) ou abaixo (negativo) do preço alvo.
- **Alvo atingido** (`reached`): a cotação já passou do alvo no sentido da operação.
