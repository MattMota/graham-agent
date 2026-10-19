---
name: rebalancear-carteira
description: Verificar se a carteira está na alocação-alvo do usuário e sugerir como rebalanceá-la, com ou sem aporte. Use quando o usuário perguntar se a carteira está enquadrada, onde aplicar um aporte ou como voltar aos pesos que ele quer.
---

# Rebalancear a carteira

A alocação-alvo é do usuário: o peso de cada classe de ativo e a banda de tolerância que ele escolheu. Você não decide os pesos nem sugere carteiras-modelo; o que vai para a carteira, ele confirma.

1. **Veja o enquadramento.** Chame `ver_enquadramento`. Pronto quando souber o peso de cada classe e se há alocação-alvo (`has_targets`).
2. **Sem alocação-alvo, combine-a com o usuário.** Mostre os pesos atuais e pergunte quanto ele quer em cada classe (ações brasileiras, fundos listados, ETFs, exterior, cripto) e a banda de tolerância (5 pontos percentuais, se ele não disser). O perfil do investidor guardado na memória pode orientar a conversa, não os números. Grave com `definir_alocacao`, que soma 100%; o usuário confirma no cartão. Pronto quando a ferramenta devolver a alocação gravada.
3. **Sugira o rebalanceamento.** Chame `sugerir_rebalanceamento` com o aporte que o usuário mencionou (`contribution`, em reais). Só passe `allow_sales` quando ele aceitar vender. Pronto quando houver as ordens sugeridas.
4. **Responda nesta estrutura:**
   - **Situação**: enquadrada ou não, e as classes fora da banda, com o desvio.
   - **Sugestão**: as ordens, o que sobra do aporte e, para uma classe sem ativo na carteira, o valor e os candidatos da watchlist, perguntando qual ativo ele quer.
   - **Pesos depois**: antes e depois, por classe, contra o alvo.
5. **Registre só o que ele pedir.** Se o usuário quiser executar, chame `registrar_compra` ou `registrar_venda` para cada ordem, com a quantidade, o preço sugerido e a data de hoje; cada uma passa pelo cartão de confirmação. Pronto quando as ferramentas devolverem as operações gravadas ou ele desistir.

Nunca apresente a sugestão como recomendação de investimento: ela é a conta para chegar ao alvo que o usuário escolheu.
