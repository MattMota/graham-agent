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
| Resposta transmitida token a token | ✅ Existente | `src/server/runs.py` | Eventos AG-UI a partir de `astream_events(version="v2")`, com os argumentos das ferramentas transmitidos enquanto o modelo os escreve |
| Tempo de pensamento | ✅ Existente | `src/server/runs.py`, `thinking_ms` no `payload` | "pensando · 12 s" enquanto o modelo raciocina sem produzir nada; o total do turno ao lado das ações. Só o tempo é medido, o raciocínio não é mostrado |
| Aba de conversas | ✅ Existente | `GET /api/threads`, `static/js/sidebar.js` | Fixa à esquerda em telas largas, gaveta nas estreitas; indica as que estão respondendo ou aguardando confirmação. Trocar de conversa no meio de uma resposta não a interrompe |
| Renomear, apagar e buscar conversas | ✅ Existente | `PATCH` e `DELETE /api/threads/{id}`, `GET /api/threads?q=` | Busca no título e nas mensagens, sem caixa nem acento, com o trecho destacado. Apagar esconde a conversa e tira os turnos dela da memória do agente; as mensagens ficam para as bifurcações |
| Nova conversa | ✅ Existente | `POST /api/agent` | O navegador gera o id na primeira pergunta, como o AG-UI espera, e o servidor cria a conversa com ele; o id fica no `localStorage` |
| Conversas gravadas no banco | ✅ Existente | `src/storage/`, `db/migrations/` | Árvore de mensagens no schema `agent`; reabrir a página redesenha o caminho ativo pelo `MESSAGES_SNAPSHOT` do AG-UI |
| Regerar resposta | ✅ Existente | `POST /api/agent`, `forwardedProps.graham.regenerate` | A nova resposta é irmã da anterior, que continua gravada fora do caminho |
| Bifurcar conversa | ✅ Existente | `POST /api/threads/{id}/fork` | Sem copiar mensagens: o fork sobe pelos `parent_id` até a origem |
| Resposta interrompida | ✅ Existente | `src/server/recorder.py` | Só quando o servidor para no meio do turno: o texto parcial é salvo e marcado, e a saída oferecida é regerar |
| Memória de longo prazo | ✅ Existente | `src/agent/memory/`, `agent.memories` | Perfil, preferências, interesses e episódios guardados pelo agente; substituição automática; esquecer sem apagar |
| Perfil sempre no contexto | ✅ Existente | `AgentContext.profile` | Perfil e preferências entram em toda resposta |
| Conversas reencontráveis | ✅ Existente | `buscar_memorias`, `ver_memoria` | Cada turno concluído vira memória `conversa`, achada por busca híbrida |
| Painel de memórias | ⏳ Pendente | | Listar e esquecer memórias pela interface |
| Checkpoints do LangGraph | ✅ Existente | `src/server/runs.py`, `src/server/app.py` | Uma thread do LangGraph por turno, guardada por um dia para inspeção |
| Sugestões de perguntas na tela inicial | ✅ Existente | `src/server/static/index.html` | |

## Dados de mercado

| Feature | Estado | Onde | Observações |
|---|---|---|---|
| Cotação atual de uma ação | ✅ Existente | `cotacao_atual_acao` | Preço, variação, volume, valor de mercado, faixa de 52 semanas e médias móveis |
| Notícias de uma ação | ✅ Existente | `noticias_acao` | O feed por ticker da Yahoo está fora do ar; as notícias vêm da busca pelo nome da empresa, sem resumo |
| Notícias de um tema | ✅ Existente | `noticias_tema` | Busca do Google News em português (RSS público, sem chave), para o que a busca da Yahoo não acha; sem resumo |
| Busca de ticker pelo nome da empresa | ✅ Existente | `buscar_ticker_por_empresa` | |
| Busca de empresas por indústria | ✅ Existente | `buscar_tickers_por_industria` | 145 subsetores da classificação Yahoo, com correção aproximada do nome |
| Proventos de um ativo | ✅ Existente | `proventos` | Pagamentos, total em 12 meses, dividend yield e próxima data ex; ações e FIIs |
| Desempenho e comparação | ✅ Existente | `desempenho` | Até 4 ativos contra o Ibovespa ou o S&P 500, por período ou desde uma data; gráfico na interface |
| Fundamentos | ⏳ Pendente | | Indicadores e evolução do P/L e P/VP; demonstrativos da Petrobras e da Vale vêm em dólar com rótulo de real e precisam de checagem |
| Consenso de analistas | ⏳ Pendente | | Preço-alvo, recomendações e estimativas de lucro |
| Agenda de eventos | ✅ Existente | `agenda_eventos` | Próximos resultados, datas ex e pagamentos da carteira e da watchlist, ou de ativos pedidos; tabela na interface. A Yahoo nem sempre tem o próximo resultado das empresas brasileiras, e esses ativos vêm à parte |
| Triagem de ações | ⏳ Pendente | | Screener com `region = br`, filtrando os BDRs |
| Resumo de mercado | ⏳ Pendente | | O schema `MarketInput` e o rótulo na interface existem, mas a ferramenta não está registrada |

## Interface

| Feature | Estado | Onde | Observações |
|---|---|---|---|
| Cartões de cotação dos tickers citados | ✅ Existente | `src/server/runs.py` | Até 8 por resposta, sem repetir consultas já feitas |
| Detalhe das consultas feitas | ✅ Existente | `static/js/tool-runs.js` | Argumentos enviados e JSON devolvido, recolhíveis. Várias consultas seguidas viram um grupo que mostra só a em andamento e a contagem |
| Análises fora das consultas | ✅ Existente | `toolRun` em `static/js/tool-runs.js`, vistas em `static/js/views.js` | Carteira, proventos, o gráfico de desempenho, a agenda de eventos, o enquadramento e o rebalanceamento aparecem entre as consultas e o texto da resposta; mais de uma no mesmo grupo, cada uma recolhida sob um título |
| Markdown nas respostas | ✅ Existente | `static/js/markdown.js` | Renderizador próprio; todo conteúdo é escapado antes de virar HTML |
| REPL de linha de comando | ✅ Existente | `main.py` | |
| Inspeção do servidor MCP | ✅ Existente | `scripts/mcp_inspector.py` | Abre o MCP Inspector conectado ao `/mcp` com uma chave temporária da conta, revogada ao fechar |
| Verificação de saúde | ✅ Existente | `GET /api/health` | |
| Subir tudo no Docker | ✅ Existente | `Dockerfile`, perfil `app` do `compose.yaml` | `docker compose --profile app up -d --build`: Postgres, Redis e o Graham, que aplica as migrations ao subir. Só em 127.0.0.1 |
| Traces na LangSmith | ✅ Existente | Variáveis `LANGSMITH_*` no `.env`, `src/server/runs.py` | Opcional. Cada turno vira um trace, agrupado por conversa na aba *Threads*. Plano gratuito sem cartão: 5.000 traces por mês, recusados depois disso, sem cobrança. Os dados vão para a nuvem da LangSmith; os testes rodam com o tracing desligado |

## Investidor

| Feature | Estado | Onde | Observações |
|---|---|---|---|
| Carteira | ✅ Existente | `src/tools/portfolio.py`, `core.portfolio_trades` | Livro de operações com preço médio, no preço e na moeda em que o usuário pagou; valor atual convertido pelo câmbio do dia; em tabela na interface |
| Proventos da carteira | ✅ Existente | `proventos` sem ticker | Pela quantidade que o usuário tinha em cada data ex |
| Watchlist | ✅ Existente | `src/tools/portfolio.py`, `core.watchlist` | Operação pretendida, preço alvo e quantidade opcional; distância até o alvo |
| Confirmação das operações | ✅ Existente | Nó `approval` do grafo, interrupções do AG-UI | Um cartão por operação, com valores editáveis exceto o ativo e listas com busca para moeda e operação; o agente sugere a cotação atual para operações de hoje |
| Cache com Redis | ✅ Existente | `src/storage/cache.py` | Notícias por 1h, buscas por 24h, cotações sem cache; as conversas ficam no Postgres, de propósito |
| Streams retomáveis | ✅ Existente | `src/server/streams.py` | A execução roda em segundo plano; recarregar a página ou perder a conexão não interrompe a resposta. Fora do AG-UI, que não define retomada: `connect` e `Last-Event-ID` |
| Alocação-alvo | ✅ Existente | `definir_alocacao`, `core.allocation_targets` | Peso de cada classe de ativo (ações brasileiras, fundos listados, ETFs, exterior, cripto), somando 100%, e banda de tolerância; confirmada no cartão. Definida pelo usuário, sem carteiras-modelo ([ADR 0004](adr/0004-alocacao-alvo-definida-pelo-usuario.md)) |
| Enquadramento | ✅ Existente | `ver_enquadramento` | Peso de cada classe e de cada ativo em reais, contra o alvo, com desvio e situação; tabela na interface. A classe sai do tipo e do nome na Yahoo |
| Rebalanceamento | ✅ Existente | `sugerir_rebalanceamento`, skill `rebalancear-carteira` | Ordens por ativo com o aporte e, se permitido, vendas; classes sem ativo trazem candidatos da watchlist. Só sugere: cada ordem é registrada depois, com o cartão |
| Classe escolhida por ativo | ✅ Existente | `definir_classe_ativo`, `core.asset_class_overrides` | A classe automática é a do instrumento (o IVVB11 é ETF, não exterior); o usuário escolhe outra para um ativo, ou o tira da conta, com o cartão. Vale só para ele |

## Qualidade

| Feature | Estado | Onde | Observações |
|---|---|---|---|
| Testes de unidade e do grafo | ✅ Existente | `tests/unit/`, `tests/graph/` | Regras da carteira, proventos, agenda, schemas e cartões; o grafo e a confirmação com um modelo roteirizado, sem provedor |
| Testes de integração | ✅ Existente | `tests/integration/` | O servidor inteiro contra Postgres e Redis de teste: MCP com chaves e permissões, turnos pelo AG-UI com confirmação, memória do turno. Cotação, eventos, embeddings e modelo fixos |
| Evals do modelo | ✅ Existente | `tests/evals/`, `-m eval` | Primeira ferramenta escolhida pelo modelo de verdade, por taxa de acerto; fora da CI porque custa tokens |
| CI | ✅ Existente | `.github/workflows/ci.yml` | Ruff e a suíte, menos os evals, a cada push na `main` e em pull requests |

## Plataforma

Features interdependentes, na ordem de implementação: cada uma depende das anteriores.

| Feature | Estado | Onde | Observações |
|---|---|---|---|
| 1. Autenticação | ✅ Existente | `src/server/auth.py`, `core.sessions` | E-mail e senha, login obrigatório; conversas, memórias, carteira e watchlist ficam na conta. O uso anônimo anterior virou a conta `user@email.com`. Sem verificação de e-mail nem recuperação de senha, por decisão |
| 2. Servidor MCP | ✅ Existente | `src/mcp_server/`, `src/tools/`, `core.access_tokens` | Mercado, análise, carteira e watchlist em `/mcp`. Agentes externos entram com chaves de acesso criadas em *Conectar agentes* (só leitura, ou com escrita se marcado); o Graham consome com um token interno por turno, e a confirmação das operações continua no grafo. A memória fica só no Graham |
| 2.a. Resources do MCP | ✅ Existente | `src/mcp_server/resources/` | Convenções, glossário, fontes e limites dos dados, catálogo de subsetores e de moedas. Só referência, nada do usuário. O Graham lê as convenções do MCP para o próprio prompt |
| 2.b. Skills do MCP | ✅ Existente | `src/mcp_server/skills/`, `skills_extension.py` | Analisar ativo, explicar movimento, revisar carteira e registrar operação, por grupo. Pela extensão SEP-2640 (conformidade verificada pelo Inspector), como prompts com argumentos e no próprio Graham, que as carrega com `ler_skill`. Padrão de criação e de variantes por argumento no `CLAUDE.md` da pasta |
| 2.c. Protocolo AG-UI | ✅ Existente | `src/server/agent.py`, `agui.py`, `runs.py` | O protocolo entre a nossa interface e o agente, só para ela: o Graham Agent fica na plataforma. O servidor continua dono do histórico. Confirmação pelas interrupções do protocolo, regenerar em `forwardedProps`, extras do Graham em `metadata.graham` |
| 2.d. Visualizações em A2UI | ⏳ Pendente | | Depende de 2 e 2.c, e espera a primeira versão estável do A2UI (a 1.0; hoje a estável é a 0.9.1). Carteira, proventos, desempenho e confirmações descritos pelas próprias ferramentas, não pelo modelo, com um catálogo do Graham para o gráfico e os cartões de ticker |

## Fora do escopo

Decidido não fazer, com o motivo. Uma linha sai daqui só revendo a decisão.

| O quê | Por quê | Onde está a decisão |
|---|---|---|
| OAuth 2.1 no MCP, conectores do claude.ai e do ChatGPT | O Graham roda só na máquina do usuário; esses conectores rodam na nuvem e nunca o alcançariam. Chegou a ser implementado e foi desfeito | [ADR 0001](adr/0001-graham-roda-so-localmente.md) |
| Protocolo A2A | Mesmo motivo; também ficaram sem resposta a autenticação do agente cliente e as confirmações | [ADR 0001](adr/0001-graham-roda-so-localmente.md) |
| Deploy, túneis, links públicos | Mesmo motivo | [ADR 0001](adr/0001-graham-roda-so-localmente.md) |
| Langfuse instalado na máquina | A LangSmith gratuita, opcional e sem cartão, evita manter mais um serviço; desligada, nada sai da máquina | [ADR 0001](adr/0001-graham-roda-so-localmente.md) |
| Deep Agents e multi-agente | Turnos curtos, de uma ou duas rodadas de ferramentas; a confirmação e o AG-UI dependem do grafo próprio | [ADR 0002](adr/0002-um-agente-so.md) |
| RAGAS e DeepEval | Os evals conferem decisões objetivas; um juiz só entra para avaliar a resposta final, e então o DeepEval | [ADR 0003](adr/0003-evals-sem-framework-de-juiz.md) |
| Carteiras-modelo por perfil | Pesos sugeridos pelo sistema seriam recomendação de investimento | [ADR 0004](adr/0004-alocacao-alvo-definida-pelo-usuario.md) |
| Último dia com direito ao provento, pelo calendário da B3 | A agenda dá a data ex e a regra (o pregão anterior); calcular o dia exige manter os feriados da B3, e não vale a complexidade | Esta tabela |
| Regras de estilo do ruff 0.17 | 144 avisos de estilo (106 de `Optional[X]` em vez de `X \| None`); o lint fica no conjunto clássico, que pega erros reais | `[tool.ruff.lint]` no `pyproject.toml` |
