---
name: revisar-carteira
description: Revisar a carteira do usuário (posições, resultado, concentração, proventos recebidos, watchlist e próximos eventos). Use quando o usuário pedir um balanço, uma revisão ou "como está" a carteira.
---

# Revisar a carteira

1. **Colete**, numa rodada só: `ver_carteira`, `proventos` sem ticker (os 12 meses da carteira), `ver_watchlist` e `agenda_eventos` sem tickers, com `days` 30. Pronto quando as quatro tiverem respondido.
2. **Calcule a concentração**: o peso de cada posição no valor atual da sua moeda. Os totais vêm separados por moeda e não se somam entre moedas. Pronto quando cada posição tiver o seu peso.
3. **Responda nesta estrutura**:
   - **Resumo**: investido, valor atual e resultado, por moeda.
   - **Posições**: as de maior peso e as de maior e menor resultado.
   - **Concentração**: posições acima de 25% do valor da moeda, se houver.
   - **Proventos**: o recebido em 12 meses.
   - **Watchlist**: alvos atingidos e os que estão a menos de 5% do preço atual.
   - **Próximos 30 dias**: resultados e datas ex, os das posições antes dos da watchlist.

Uma carteira vazia pede uma resposta curta: diga que não há operações registradas e como registrar uma.
