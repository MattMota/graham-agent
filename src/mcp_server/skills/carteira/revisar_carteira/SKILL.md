---
name: revisar-carteira
description: Revisar a carteira do usuário (posições, resultado, concentração, proventos recebidos e watchlist). Use quando o usuário pedir um balanço, uma revisão ou "como está" a carteira.
---

# Revisar a carteira

1. **Colete**, numa rodada só: `ver_carteira`, `proventos` sem ticker (os 12 meses da carteira) e `ver_watchlist`. Pronto quando as três tiverem respondido.
2. **Calcule a concentração**: o peso de cada posição no valor atual da sua moeda. Os totais vêm separados por moeda e não se somam entre moedas. Pronto quando cada posição tiver o seu peso.
3. **Responda nesta estrutura**:
   - **Resumo**: investido, valor atual e resultado, por moeda.
   - **Posições**: as de maior peso e as de maior e menor resultado.
   - **Concentração**: posições acima de 25% do valor da moeda, se houver.
   - **Proventos**: o recebido em 12 meses e as próximas datas ex das posições.
   - **Watchlist**: alvos atingidos e os que estão a menos de 5% do preço atual.

Uma carteira vazia pede uma resposta curta: diga que não há operações registradas e como registrar uma.
