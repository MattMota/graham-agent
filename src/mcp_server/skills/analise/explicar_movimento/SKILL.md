---
name: explicar-movimento
description: Explicar por que um ativo subiu ou caiu num período. Use quando o usuário perguntar o motivo de uma alta, queda ou oscilação.
---

# Explicar o movimento de um ativo

O objetivo é uma explicação sustentada por fontes, não um palpite: cada causa citada aponta para uma notícia com veículo e data.

1. **Meça o movimento.** Chame `desempenho` com o ativo no período em questão (`1mo` se o usuário não disser). Pronto quando você souber quanto o ativo variou e se o índice de referência acompanhou: um movimento igual ao do índice tem causa de mercado, não da empresa.
2. **Busque as notícias da empresa.** Chame `noticias_acao`. Pronto quando cada notícia do período estiver classificada como relacionada ao movimento ou não.
3. **Busque o tema por trás.** Se as notícias da empresa não explicarem o movimento, ou se o contexto sugerir algo maior (eleição, decisão do Banco Central, regulação do setor, mudança de governo), chame `noticias_tema` com palavras-chave que identifiquem o tema, como "privatização Banco do Brasil". Pronto quando houver uma causa sustentada ou a constatação de que não há notícia que explique.
4. **Responda.** Dê a variação do ativo e a do índice, e as causas mais prováveis, cada uma com o veículo e a data da notícia. Sem causa encontrada, diga isso: um movimento sem notícia pode ser fluxo de mercado.

As notícias trazem só o título: atribua cada informação ao veículo e não afirme além do que o título diz.
