# Graham

Um agente de investimentos pessoal: responde sobre o mercado, guarda a carteira e a watchlist do usuário e analisa a carteira contra o que ele definiu.

## Carteira

**Operação**:
Uma compra ou venda registrada pelo usuário, com ativo, quantidade, preço unitário, moeda do preço e data. Nunca muda depois de gravada.
_Avoid_: trade, transação, ordem

**Carteira**:
O livro de operações do usuário e as posições que saem dele.
_Avoid_: portfólio

**Posição**:
O que o usuário tem de um ativo depois de aplicadas as operações em ordem de data: quantidade e preço médio.
_Avoid_: holding, ativo da carteira

**Preço médio**:
A média ponderada das compras de um ativo; uma venda reduz a quantidade sem mudá-lo.
_Avoid_: custo médio, PM

**Resultado**:
O valor atual de uma posição em aberto menos o investido nela.
_Avoid_: lucro, rentabilidade

**Resultado realizado**:
O ganho ou a perda das vendas já feitas, medido contra o preço médio do momento de cada venda.

## Watchlist

**Entrada da watchlist**:
Um ativo que o usuário acompanha com uma operação pretendida (compra, venda ou short), um preço alvo e, opcionalmente, uma quantidade.
_Avoid_: alerta, favorito

**Alvo atingido**:
A cotação passou do preço alvo no sentido da operação pretendida.

## Proventos e eventos

**Provento**:
Dinheiro distribuído ao acionista ou cotista: dividendos, juros sobre capital próprio e rendimentos de fundos imobiliários.
_Avoid_: dividendo (quando se quer dizer todos os tipos)

**Data ex**:
O primeiro dia em que o ativo é negociado sem o direito ao provento; tem direito quem tinha o ativo no fim do pregão anterior.
_Avoid_: data com, data de corte

**Evento**:
Uma data futura de um ativo: divulgação de resultado, data ex ou pagamento de provento.

**Agenda**:
Os próximos eventos dos ativos da carteira e da watchlist, ou dos ativos pedidos, em ordem de data.
_Avoid_: calendário

## Alocação

**Classe de ativo**:
O grupo em que a alocação conta um ativo: ações brasileiras, fundos listados (FIIs, Fiagros, FI-Infra), ETFs (da B3 e de fora), exterior (ações estrangeiras e BDRs) ou cripto. Automática pelo tipo de instrumento, a menos que o usuário tenha escolhido outra para aquele ativo.
_Avoid_: setor, categoria

**Classe escolhida**:
A classe que o usuário definiu para um ativo, no lugar da automática; vale só para a carteira dele. Pode ser "fora", que tira o ativo da conta.
_Avoid_: reclassificação, override

**Alocação-alvo**:
O peso que o usuário quer para cada classe de ativo na carteira, somando 100%, com uma banda de tolerância. Definida e confirmada pelo usuário.
_Avoid_: perfil de alocação, carteira-modelo, carteira recomendada

**Banda de tolerância**:
Quantos pontos percentuais o peso de uma classe pode se afastar do alvo antes de a carteira ficar desenquadrada.

**Peso**:
A fração do valor da carteira, em reais, que está numa classe de ativo ou num ativo.

**Enquadramento**:
A comparação dos pesos atuais da carteira com a alocação-alvo. A carteira está enquadrada quando toda classe está dentro da banda; desenquadrada quando alguma está fora.
_Avoid_: aderência, compliance

**Rebalanceamento**:
As compras, e opcionalmente vendas, que levariam os pesos da carteira à alocação-alvo. É uma sugestão: só vira operação quando o usuário confirma cada uma.
_Avoid_: ajuste, realocação

**Aporte**:
Dinheiro novo que o usuário vai investir, usado no rebalanceamento antes de qualquer venda.
_Avoid_: depósito, contribuição

**Perfil do investidor**:
O que o usuário contou sobre si (tolerância a risco, horizonte, objetivos), guardado na memória como texto. Orienta a conversa, mas não é a alocação-alvo.
_Avoid_: suitability, perfil de risco (quando se quer dizer a alocação-alvo)

## Conversa

**Conversa**:
Uma sequência de turnos entre o usuário e o agente, com título, que pode ser bifurcada.
_Avoid_: thread, chat, sessão

**Turno**:
Uma pergunta do usuário e tudo o que o agente fez para respondê-la, até a resposta final ou uma confirmação pendente.

**Confirmação**:
O cartão em que o usuário aprova, corrige ou cancela uma operação que o agente quer gravar.
_Avoid_: aprovação (na conversa com o usuário), human-in-the-loop

**Memória**:
Um fato duradouro sobre o usuário, ou um turno já concluído, guardado para as próximas conversas.

**Skill**:
Um roteiro para uma tarefa recorrente (analisar um ativo, revisar a carteira), que o agente carrega quando a tarefa pede.

**Chave de acesso**:
O que um agente externo usa para chamar as ferramentas do Graham em nome do usuário, só com leitura ou também com escrita.
_Avoid_: token, API key
