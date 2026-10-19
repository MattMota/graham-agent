# Persistência, cache e autenticação

O que fica no Postgres, o que fica no Redis e como o usuário entra.

## Conversas no banco

O histórico da conversa vive nas tabelas do schema `agent`, e não no checkpointer. As mensagens formam uma **árvore**: cada uma aponta para a anterior (`parent_id`), e a thread guarda a última do caminho ativo (`head_message_id`).

- **Continuar** acrescenta uma pergunta embaixo da `head`.
- **Regerar** cria uma nova resposta como irmã da anterior, pendurada na mesma pergunta. A resposta antiga continua gravada, fora do caminho.
- **Bifurcar** cria uma thread cuja `head` é a mensagem escolhida. Nada é copiado: o caminho do fork sobe pelos `parent_id` até a thread de origem.

**Apagar é esconder.** `DELETE /api/threads/{id}` grava `deleted_at`, e a conversa some da lista, da busca e do acesso. As mensagens ficam, porque uma bifurcação sobe pelos `parent_id` até elas. As memórias `conversa` dos turnos dela, que são só o índice de busca desses turnos, saem de vez, e o agente não a reencontra mais; os fatos sobre o usuário guardados naquela conversa continuam. A busca de conversas ignora caixa e acentos (`unaccent`).

`agent.thread_path` devolve o caminho ativo em ordem, e é dele que sai o histórico entregue ao modelo a cada turno. Respostas interrompidas ou com erro ficam fora desse histórico, assim como pedidos de ferramenta que nunca receberam resposta, que os provedores recusam.

Cada mensagem tem um estado: `streaming` enquanto é gerada, `awaiting_approval` enquanto o turno espera a confirmação de uma operação, depois `completed`, `interrupted` (o servidor parou no meio do turno ou a confirmação foi abandonada) ou `failed`. Quando o servidor sobe, o que ficou em `streaming` vira `interrupted`.

## Cache

| O quê | Chave | TTL | Observações |
|---|---|---|---|
| Notícias | `graham:market:noticias_acao:*`, `graham:market:noticias_tema:*` | 1h | Resultado vazio não entra no cache: pode ser a fonte fora do ar |
| Proventos de um ativo | `graham:market:proventos:*` | 24h | |
| Datas de eventos | `graham:market:eventos:*` | 6h | Resultado, data ex e pagamento de um ativo; uma data ex pode ser anunciada para o dia seguinte |
| Histórico de preços | `graham:market:historico:*` | 1h | |
| Busca de ticker e triagem por setor | `graham:market:buscar_*:*` | 24h | Mudam raramente |
| Classe de ativo | `graham:market:classe:*` | 7 dias | O tipo e o nome de um ativo na Yahoo quase nunca mudam |
| Cotação | | | **Sem cache:** muda a todo momento, e um preço velho é pior do que nenhum |

As conversas ficam fora do cache de propósito. Ler o caminho de uma thread no Postgres custa cerca de 1 ms, nada perto dos segundos de um turno, quase todos à espera do modelo. Uma cópia no Redis ocuparia memória proporcional às conversas ativas e traria o risco de mostrar uma versão desatualizada, em troca de um ganho que não aparece. O cache que faz diferença para a conversa é o do provedor do modelo, que reaproveita o começo do prompt entre chamadas; como o histórico só cresce no fim, ele já se beneficia disso.

O cache de mercado falha aberto: se o Redis não responder, os dados vêm direto da Yahoo. Os streams, não: sem Redis, o servidor não sobe.

## Autenticação

O usuário entra com e-mail e senha, e tudo o que é dele (conversas, memórias, carteira, watchlist) aponta para `core.users`. Sem sessão, a interface mostra só a tela de entrada, e as rotas respondem `401`.

- **Sessão guardada no servidor.** O cookie `graham_session` (`HttpOnly`, `SameSite=Lax`) leva um token aleatório; `core.sessions` guarda só o SHA-256 dele, e uma cópia do banco não serve para entrar. Sair apaga a sessão, que deixa de valer na hora. Ela dura 30 dias, e as vencidas são apagadas de hora em hora.
- **Senhas com bcrypt**, custo 12, calculado fora do event loop. Na criação de conta, a senha precisa de 8 caracteres; acima de 72 bytes, o bcrypt a truncaria, e ela é recusada.
- **Sem revelar quem tem conta no login.** E-mail inexistente e senha errada dão a mesma resposta, no mesmo tempo: um hash é conferido mesmo sem conta.
- **Força bruta.** Dez senhas erradas para o mesmo e-mail bloqueiam o login dele por 15 minutos (contador no Redis).
- **Fora do escopo, por decisão:** verificação de e-mail e recuperação de senha.
