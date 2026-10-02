# Features

Estado de cada funcionalidade do Graham Agent. Atualize a linha quando uma feature mudar de estado.

| Estado | Significado |
|---|---|
| ✅ Existente | Implementada e disponível |
| ⏳ Pendente | Decidida, ainda não implementada |

---

## Conversa

| Feature | Estado | Onde | Observações |
|---|---|---|---|
| Perguntas em linguagem natural | ✅ Existente | `src/agent/runtime/state_graph.py` | Ciclo ReAct de dois nós (`agent` e `tools`) no LangGraph |
| Resposta transmitida token a token | ✅ Existente | `src/server/app.py` | SSE a partir de `astream_events(version="v2")` |
| Nova conversa | ✅ Existente | `POST /api/chat` | Criada pelo servidor na primeira pergunta; o navegador guarda o id no `localStorage` |
| Conversas gravadas no banco | ✅ Existente | `src/storage/`, `db/migrations/` | Árvore de mensagens no schema `agent`; reabrir a página redesenha o caminho ativo |
| Regerar resposta | ✅ Existente | `POST /api/regenerate` | A nova resposta é irmã da anterior, que continua gravada fora do caminho |
| Bifurcar conversa | ✅ Existente | `POST /api/threads/{id}/fork` | Sem copiar mensagens: o fork sobe pelos `parent_id` até a origem |
| Resposta interrompida | ✅ Existente | `src/server/recorder.py` | O texto parcial é salvo e marcado; a saída oferecida é regerar |
| Usuário anônimo | ✅ Existente | `POST /api/session` | Cookie assinado com HMAC; a autenticação entra depois em `core` |
| Checkpoints do LangGraph | ✅ Existente | `src/server/app.py` | Uma thread do LangGraph por turno, guardada por um dia para inspeção |
| Sugestões de perguntas na tela inicial | ✅ Existente | `src/server/static/index.html` | |

## Dados de mercado

| Feature | Estado | Onde | Observações |
|---|---|---|---|
| Cotação atual de uma ação | ✅ Existente | `cotacao_atual_acao` | Preço, variação, volume, valor de mercado, faixa de 52 semanas e médias móveis |
| Notícias de uma ação | ✅ Existente | `noticias_acao` | Abas de notícias, comunicados ou ambas |
| Busca de ticker pelo nome da empresa | ✅ Existente | `buscar_ticker_por_empresa` | |
| Busca de empresas por indústria | ✅ Existente | `buscar_tickers_por_industria` | 145 subsetores da classificação Yahoo, com correção aproximada do nome |

## Interface

| Feature | Estado | Onde | Observações |
|---|---|---|---|
| Cartões de cotação dos tickers citados | ✅ Existente | `src/server/app.py` | Até 8 por resposta, sem repetir consultas já feitas |
| Detalhe das consultas feitas | ✅ Existente | `src/server/static/app.js` | Argumentos enviados e JSON devolvido, recolhíveis |
| Markdown nas respostas | ✅ Existente | `src/server/static/app.js` | Renderizador próprio; todo conteúdo é escapado antes de virar HTML |
| REPL de linha de comando | ✅ Existente | `main.py` | |
| Verificação de saúde | ✅ Existente | `GET /api/health` | |

## Investidor

| Feature | Estado | Onde | Observações |
|---|---|---|---|
| Carteira | ✅ Existente | `src/agent/tools/portfolio.py`, `core.portfolio_trades` | Livro de operações com preço médio, no preço e na moeda em que o usuário pagou; valor atual convertido pelo câmbio do dia; em tabela na interface |
| Watchlist | ✅ Existente | `src/agent/tools/portfolio.py`, `core.watchlist` | Operação pretendida, preço alvo e quantidade opcional; distância até o alvo |
| Confirmação das operações | ✅ Existente | Nó `approval` do grafo, `POST /api/approvals` | Um cartão por operação, com valores editáveis exceto o ativo; o agente sugere a cotação atual para operações de hoje |
| Cache com Redis | ⏳ Pendente | | Dados de mercado (sem cotações), histórico da conversa e streams retomáveis, com TTL de 1h |
