---
name: registrar-operacao
description: Registrar uma compra ou venda na carteira com os dados certos. Use antes de chamar registrar_compra ou registrar_venda.
---

# Registrar uma operação

Uma operação gravada com o ativo, o preço ou a moeda errados distorce o preço médio e todo resultado calculado depois dela.

1. **Confirme o ativo.** Com só o nome da empresa, chame `buscar_ticker_por_empresa` e use a listagem da B3 (`.SA`) para empresas brasileiras: a busca devolve também outras bolsas. Pronto quando o ticker estiver confirmado.
2. **Confirme o preço.** Para uma operação de hoje sem preço informado, chame `cotacao_atual_acao` e use a cotação como sugestão. Para uma operação passada sem preço, pergunte ao usuário. Pronto quando houver um preço dito pelo usuário ou tirado da cotação de hoje.
3. **Confirme a moeda.** O preço fica na moeda em que o usuário pagou, informada em `currency` quando difere da cotação (Bitcoin pago em reais é `BTC-USD` com `currency` `BRL`). Pronto quando a moeda do preço estiver definida.
4. **Grave.** Chame `registrar_compra` ou `registrar_venda` com ativo, quantidade, preço, data e moeda. Uma venda maior que a posição na data é recusada: mostre a posição ao usuário em vez de tentar de novo.
5. **Informe** o que foi gravado e a posição resultante, como a ferramenta devolveu.
