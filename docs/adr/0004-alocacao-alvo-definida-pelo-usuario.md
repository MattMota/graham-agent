# Alocação-alvo por classe de ativo, definida pelo usuário

O enquadramento e o rebalanceamento comparam a carteira com uma alocação-alvo que o próprio usuário define e confirma num cartão: um peso para cada classe de ativo (ações brasileiras, fundos listados, ETFs, exterior, cripto) e uma banda de tolerância. O Graham não traz carteiras-modelo por perfil (conservador, moderado, arrojado) nem decide os pesos sozinho a partir do perfil do investidor. Pesos sugeridos pelo sistema seriam recomendação de investimento, e o projeto não faz recomendação. O agente pode conversar sobre o perfil e propor pesos, mas só grava o que o usuário confirma.

## Considered Options

- **Carteiras-modelo por perfil**: o mais comum em plataformas de investimento, e o que "perfis de alocação" costuma querer dizer. Ficou de fora porque exigiria uma política de suitability e uma responsabilidade que um projeto pessoal não tem.
- **Alvo por ativo**, em vez de por classe: mais preciso, mas obriga a redefinir o alvo a cada compra de um ativo novo. Por classe, o alvo sobrevive às trocas de ativo dentro dela.
- **O perfil do investidor da memória como alvo**: é texto livre ("perfil conservador"), sem números. Ele orienta a conversa, mas não é a alocação-alvo.

## Consequences

- **A classe sai da Yahoo, com regras próprias.** A Yahoo marca FIIs e ETFs da B3 como `EQUITY`, então a classe vem do tipo e do nome. Cripto e ETFs americanos têm tipo próprio. BDRs se reconhecem pelo código terminado em 31 a 35 ou 39. ETFs da B3 têm "índice" ou "ETF" no nome, e fundos listados têm "fundo" ou "Fiagro". Um ativo que nada disso classifica fica em "outros", fora da alocação. Se essas regras errarem com frequência, o passo seguinte é deixar o usuário corrigir a classe de um ativo.
- **Os pesos são medidos em reais.** Os valores de cada posição são convertidos pelo câmbio do momento. É a única conta do Graham que soma moedas diferentes; os totais da carteira continuam separados por moeda.
- **O rebalanceamento é uma sugestão.** Ele usa primeiro o aporte e só vende quando o usuário pede. Cada compra ou venda sugerida só vira operação pelas ferramentas de registro, com o cartão de confirmação.
