# A interface e o AG-UI

O protocolo entre a interface e o agente, os streams retomáveis e o que a tela recebe.

## O protocolo

A nossa interface e o agente conversam por [AG-UI](https://docs.ag-ui.com), o protocolo aberto entre agentes e interfaces, em `/api/agent`. Só ela usa essas rotas, com o cookie da sessão: o Graham Agent fica nesta plataforma. Para fora, há só o servidor MCP, com as ferramentas. A escolha é por um contrato padrão entre a tela e o agente (trocar um lado sem mexer no outro, usar componentes prontos e, depois, o A2UI por cima dele), não por capacidade: retomar a leitura de uma resposta, o tempo de pensamento e os cartões de ticker são do Graham, fora do protocolo. O AG-UI é um dos padrões que estão se consolidando (LangGraph, o Agent Framework da Microsoft, CopilotKit), não o único.

- **O servidor é a fonte da verdade do histórico.** O `threadId` é o id da conversa, e das `messages` de uma execução o servidor usa só a pergunta nova: a última, se for do usuário e o id dela ainda não estiver gravado. O resto que o cliente reenviar é ignorado. Com o cliente como fonte da verdade, ele poderia fabricar resultados de ferramenta, falas do agente ou confirmações de operação, e o Graham grava na carteira, depende da confirmação humana e forma memória a partir dos turnos. A API de *responses* da OpenAI (`previous_response_id`) segue o mesmo meio-termo.
- **Ids do cliente.** O cliente gera o `threadId` de uma conversa nova (o servidor a cria com ele), o `runId` de cada execução e o id da pergunta, que vira o id da linha no banco.
- **Regerar** é uma execução com `forwardedProps: {"graham": {"regenerate": "<id da resposta>"}}`, sem inferir nada comparando o histórico enviado. **Bifurcar continua REST**: só cria a conversa, e as execuções seguintes usam o novo `threadId`. Também ficam REST a lista, a busca, renomear e apagar conversas, as chaves e a conta.
- **Religar** (`POST /api/agent/connect`, como a rota `connect` do CopilotKit): uma execução que só ressincroniza (o `MESSAGES_SNAPSHOT` do caminho gravado e, se a conversa espera confirmação, o fim com as interrupções abertas) e, havendo uma execução em andamento, os eventos dela desde o começo. A interface redesenha toda conversa que abre assim.
- **Os extras do Graham vão em `metadata.graham`**, que o AG-UI deixa livre em todo evento e mensagem: o estado de cada resposta, o tempo de pensamento, o gráfico, o id da mensagem que fecha o turno, os campos travados do cartão. O fluxo básico (perguntar, receber a resposta, confirmar operações) é AG-UI padrão; regerar e os extras são do Graham. Ferramentas definidas pelo cliente (`tools`), contexto e estado compartilhado são ignorados.
- **Sem o adaptador pronto.** O `ag-ui-langgraph` passaria por cima do gravador no banco, da confirmação pelo nosso grafo e dos streams retomáveis, como o cliente MCP do LangChain passaria. Do pacote `ag-ui-protocol` vêm só os tipos.

## Streams retomáveis

Uma execução não depende da conexão do cliente. O servidor roda a execução em segundo plano e grava cada evento AG-UI num **Redis Stream**, com o `runId` como id; a resposta HTTP só lê desse stream. Se a conexão cair (a página recarregou, a rede piscou), a execução continua até o fim e é gravada inteira. O AG-UI não define retomada (a especificação do transporte diz que um stream interrompido não pode ser reaberto); ela é do Graham, pelo padrão do SSE.

- **Recarregar a página no meio de uma resposta:** o `connect` devolve o snapshot até a mensagem de onde a execução parte e, em seguida, os eventos dela desde o começo. A interface redesenha o resto e continua ao vivo.
- **A conexão cair sem recarregar:** cada evento traz o id do Redis no campo `id:` do SSE. A interface reconecta em `GET /api/agent/runs/{runId}/events` com o cabeçalho `Last-Event-ID` (o que o `EventSource` manda sozinho) ou `?after=`, e recebe só o que faltou.
- **Trocar de conversa no meio de uma resposta:** a interface só larga a leitura do stream; o turno segue no servidor. A aba de conversas marca a conversa como "respondendo" e, ao voltar a ela, a resposta é retomada como numa recarga.
- **Uma execução por conversa:** enquanto há uma em andamento, outra pergunta, regeneração ou confirmação na mesma conversa recebe `409`, assim como um `runId` repetido. Conversas diferentes respondem ao mesmo tempo.
- **O servidor parar no meio:** na subida seguinte, a mensagem em geração vira `interrupted` no Postgres, e o stream recebe um `RUN_ERROR` com `code: "interrupted"`, para quem estiver lendo saber que acabou.

Os streams duram 1h no Redis (`graham:stream:{id}`), assim como a reserva da conversa (`graham:thread:{id}:active`).

## Eventos

| Evento | Quando | Extras do Graham (`metadata.graham`) |
|---|---|---|
| `RUN_STARTED` | Início da execução, com `threadId`, `runId` e `protocolVersion` | |
| `REASONING_START` / `REASONING_END` | Cada chamada ao modelo, até a primeira saída dele; o `timestamp` do início deixa quem reconecta continuar a contagem. Sem `REASONING_MESSAGE_*`: o raciocínio não é lido, só medido | `ms` no fim |
| `TEXT_MESSAGE_START` / `CONTENT` / `END` | O texto, com `messageId` = a mensagem do assistente no banco | |
| `TOOL_CALL_START` / `ARGS` / `END` | Cada chamada de ferramenta, com os argumentos transmitidos enquanto o modelo os escreve; `parentMessageId` = a mensagem do assistente | `approval: true` nas operações que pedem confirmação |
| `TOOL_CALL_RESULT` | O resultado, com `messageId` = a mensagem da ferramenta no banco | `status` (`completed`, `failed`, `cancelled`) e `artifact` (o gráfico) |
| `CUSTOM` `graham.tickers` | Os cartões dos tickers citados, antes do fim | |
| `RUN_FINISHED` | Fim; com `outcome.type: "interrupt"`, a pausa para confirmação, uma interrupção por operação (`reason: "tool_call"`, `responseSchema` com `approved` e `editedArgs`, `expiresAt`) | `messageId`, a mensagem que fecha o turno; na interrupção, `name`, `args` e `locked` |
| `RUN_ERROR` | Falha da execução; com `code`, uma entrada recusada (`pending_interrupts`, `incomplete_resume`, `invalid_args`, `expired`, `no_pending`, `no_input`) ou o servidor parou (`interrupted`) | `messageId` da resposta que falhou |
| `MESSAGES_SNAPSHOT` | Só no `connect`: o caminho ativo da conversa | `title`, `forkedFromMessageId` e `activeRunId`; em cada mensagem, o estado, o tempo de pensamento, o gráfico e as confirmações |

## Rotas

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/auth/signup` | Recebe `{email, password}`, cria a conta e já entra |
| `POST` | `/api/auth/login` | Recebe `{email, password}` e grava o cookie de sessão |
| `POST` | `/api/auth/logout` | Apaga a sessão |
| `GET` | `/api/auth/me` | O e-mail da sessão, ou `401` |
| `POST` | `/api/agent` | AG-UI: recebe um `RunAgentInput` (pergunta nova, `resume` ou regeneração) e transmite a execução em SSE |
| `POST` | `/api/agent/connect` | Recebe `{threadId}`: o snapshot da conversa e a execução em andamento, se houver |
| `GET` | `/api/agent/runs/{runId}/events` | Retoma a leitura de uma execução depois do `Last-Event-ID` (ou `?after=`) |
| `POST` | `/api/threads/{id}/fork` | Recebe `{message_id}` e devolve a nova conversa |
| `GET` | `/api/threads` | As conversas do usuário (até 100), da atividade mais recente à mais antiga, com o status `streaming` ou `awaiting_approval`; com `?q=`, só as que têm o texto no título ou nas mensagens, com o trecho encontrado |
| `PATCH` | `/api/threads/{id}` | Recebe `{title}` e renomeia a conversa |
| `DELETE` | `/api/threads/{id}` | Apaga a conversa; `409` se houver resposta em andamento |
| `GET` | `/api/keys` | As chaves de acesso ativas (sem o valor) e a URL do servidor MCP |
| `POST` | `/api/keys` | Recebe `{name, can_write}` e cria uma chave; o valor vem só nesta resposta |
| `DELETE` | `/api/keys/{id}` | Revoga a chave |
| `POST` | `/mcp` | Servidor MCP (Streamable HTTP), com `Authorization: Bearer` |
| `GET` | `/.well-known/oauth-protected-resource/mcp` | Metadados do recurso protegido (RFC 9728) |
| `GET` | `/api/health` | Confirma que o grafo compilou e lista seus nós |
| `GET` | `/` | A interface |
| `GET` | `/static/*` | CSS e JavaScript |

## Cartões de ticker

Ao final de cada resposta, os tickers citados viram cartões. A lista é o cruzamento de duas condições: o ticker passou por alguma ferramenta (logo, existe) **e** foi de fato mencionado no texto da resposta.

Citado por extenso (`BBAS3.SA`), o ticker sempre conta. Citado só pela base (`BBAS3`), vale uma listagem dela: a busca por empresa devolve também as de outras bolsas (`BBAS3.BA`, em Buenos Aires, cotada em peso), e o cartão seria de um ativo de que o agente não falou. Fica a que o agente consultou, senão a da B3, senão a primeira da busca.

Quando o agente já consultou `cotacao_atual_acao`, a cotação completa vem de graça no próprio `on_tool_end` — nenhuma consulta é repetida. Só os tickers que apareceram por outro caminho são buscados, em paralelo e depois que a resposta terminou de ser transmitida. O teto é de 8 cartões por resposta.

Os cartões não são gravados: ao reabrir uma conversa, as respostas e as consultas voltam, mas os cartões não.

## Decisões de implementação

**O front-end não tem dependências.** O Markdown das respostas é renderizado por uma função de ~40 linhas em `app.js`, em vez de uma biblioteca de CDN. Tudo é escapado antes de virar HTML, então nada que o modelo ou a Yahoo devolvam pode injetar markup.
