# Convenções das ferramentas do Graham

Como as ferramentas leem os argumentos e escrevem os resultados. Vale para todas, salvo quando a descrição da ferramenta diz outra coisa.

## Ativos

- Os códigos seguem a Yahoo Finance. Ações e fundos imobiliários da B3 levam o sufixo `.SA` (`PETR4.SA`, `HGLG11.SA`); ações americanas vão sem sufixo (`AAPL`); criptomoedas vêm com a moeda (`BTC-USD`).
- Maiúsculas e minúsculas tanto faz: `petr4.sa` vira `PETR4.SA`.
- Só com o nome da empresa, descubra o código com `buscar_ticker_por_empresa`. A busca devolve também as listagens em outras bolsas: o Banco do Brasil aparece como `BBAS3.SA` (B3) e `BBAS3.BA` (Buenos Aires, em peso argentino). Para uma empresa brasileira, use a da B3.
- Os índices de referência do desempenho são o Ibovespa (`^BVSP`), para quando há algum ativo da B3, e o S&P 500 (`^GSPC`), para os demais.

## Moedas

- Códigos ISO 4217 (`BRL`, `USD`, `EUR`). Cada valor de mercado está na moeda da cotação do ativo, informada no campo `currency`.
- Na carteira, o preço de uma operação fica na moeda em que o usuário pagou, que pode não ser a da cotação (Bitcoin pago em reais é `BTC-USD` com `currency` `BRL`). O valor atual é convertido para essa moeda pelo câmbio do dia, informado em `exchange_rate`.
- Os totais da carteira vêm separados por moeda e nunca são somados entre moedas diferentes.

## Números e datas

- Campos terminados em `_percent` estão em pontos percentuais: `12.5` quer dizer 12,5%, não 1.250%.
- Números usam ponto como separador decimal. Quantidades podem ser fracionárias (criptomoedas).
- Datas vêm em ISO 8601, `AAAA-MM-DD`; horários, com o fuso: as cotações, em UTC (`2026-10-10T20:08:00Z`), e o fuso da bolsa vem à parte, em `timezone`. "Hoje" é a data do servidor do Graham.
- Períodos do desempenho: `1mo`, `3mo`, `6mo`, `ytd` (desde o início do ano), `1y`, `2y`, `5y`, `10y` e `max`. Uma `start_date` substitui o período.

## Resultados

- Um campo `note` explica como ler o resultado (o que os valores incluem, de onde vieram). Leia antes de concluir.
- Um campo `unavailable` lista o que não pôde ser consultado, sem derrubar o resto do resultado.
- Uma falha prevista (ativo inexistente, venda maior que a posição) volta como erro da ferramenta, com a explicação em português. Corrija o pedido em vez de repetir.

## Escrita

- `registrar_compra`, `registrar_venda`, `adicionar_watchlist`, `remover_watchlist` e `definir_alocacao` gravam na conta do dono da chave. Exigem uma chave com a permissão de escrita e vêm anotadas como destrutivas: confirme com o usuário antes de chamá-las.
- Nunca invente o preço de uma operação passada; pergunte. Para uma operação de hoje sem preço informado, a cotação atual serve de sugestão.
- Os pesos da alocação-alvo são escolha do usuário. Pergunte ou confirme com ele; não os decida a partir do perfil.
