---
name: analisar-ativo
description: Fazer a análise padrão de um ativo (preço, desempenho contra o índice, proventos e notícias). Use quando o usuário pedir uma análise, uma visão geral ou "o que você acha" de um ativo.
---

# Analisar um ativo

Uma leitura completa e comparável entre ativos: os mesmos dados, na mesma ordem, sempre.

1. **Identifique o ativo.** Com só o nome da empresa, chame `buscar_ticker_por_empresa` e use a listagem da B3 (`.SA`) para empresas brasileiras. Pronto quando houver um ticker confirmado pela cotação.
2. **Colete os dados**, numa rodada só:
   - `cotacao_atual_acao`: preço, variação do dia, faixa de 52 semanas;
   - `desempenho` com `period` `1y`: retorno com proventos, volatilidade e maior queda contra o índice;
   - `proventos`: total em 12 meses, dividend yield e próxima data ex;
   - `noticias_acao`: o que se publica sobre a empresa.

   Pronto quando as quatro tiverem respondido ou o que faltou estiver anotado em `unavailable`.
3. **Responda nesta estrutura**:
   - **Preço**: onde está e onde fica na faixa de 52 semanas.
   - **Desempenho**: retorno de 1 ano contra o índice, volatilidade e maior queda.
   - **Proventos**: o que pagou em 12 meses e o dividend yield.
   - **Notícias**: os fatos recentes relevantes, com veículo e data.
   - **Leitura**: um parágrafo que liga os pontos.

Os dados descrevem o passado: apresente-os como análise, sem recomendar compra ou venda.
