# Graham Agent

> Seu corretor de confiança.

Um agente conversacional que responde perguntas sobre ações, empresas e setores consultando a Yahoo Finance em tempo real. O nome é uma homenagem a Benjamin Graham, e a interface segue essa ideia: papel off-white, tipografia serifada e respostas que se leem com calma, sem o ruído de um terminal de operações.

O projeto é de estudo. As cotações vêm com atraso e nada aqui é recomendação de investimento.

---

## O que ele faz

Você pergunta em linguagem natural — *"Quanto vale BBAS3 hoje?"*, *"Notícias da Petrobras"*, *"Compare ouro e Bitcoin"* — e o agente decide sozinho quais consultas precisa fazer, executa e explica o resultado.

A resposta chega **token a token**, com os dados aparecendo conforme são buscados. Ao final, os tickers citados viram cartões de cotação recolhíveis, e cada consulta feita pode ser aberta para inspeção (argumentos enviados e JSON devolvido).

### Ferramentas disponíveis ao agente

| Ferramenta | Argumentos | O que retorna |
|---|---|---|
| `cotacao_atual_acao` | `ticker_name` | Preço, variação do dia, abertura, máxima/mínima, volume, valor de mercado, faixa de 52 semanas e médias móveis |
| `noticias_acao` | `ticker_name`, `count`, `tab` | Notícias recentes com título, resumo, data, veículo e link |
| `noticias_tema` | `query`, `days`, `count` | Notícias de um tema (eleições, privatizações, juros, um setor) em fontes brasileiras, pela busca do Google News |
| `buscar_ticker_por_empresa` | `company_name`, `count` | Tickers correspondentes a um nome de empresa, com bolsa, setor e indústria |
| `buscar_tickers_por_industria` | `industry`, `count`, `region` | Principais empresas de um dos 145 subsetores da classificação Yahoo |
| `ver_carteira` | `ticker_name?`, `currency?`, `include_trades?` | Posições com preço médio, total investido, valor atual e resultado, totais por moeda e resultado das vendas |
| `ver_watchlist` | `ticker_name?` | Entradas da watchlist com a cotação atual, a distância até o alvo e se ele foi atingido |
| `registrar_compra` ✋ | `ticker_name`, `quantity`, `unit_price`, `traded_on`, `currency?` | A operação gravada e a posição nova |
| `registrar_venda` ✋ | `ticker_name`, `quantity`, `unit_price`, `traded_on`, `currency?` | A operação gravada e a posição nova; recusa vender mais do que havia na data |
| `adicionar_watchlist` ✋ | `ticker_name`, `operation`, `target_price`, `quantity?` | A entrada criada |
| `remover_watchlist` ✋ | `ticker_name`, `operation`, `target_price?` | A entrada removida |
| `proventos` | `ticker_name?`, `months` | Pagamentos pela data ex, total em 12 meses, dividend yield e próxima data ex; sem ticker, quanto a carteira recebeu |
| `desempenho` | `tickers`, `period` ou `start_date`, `compare_index` | Retorno com e sem proventos, anualizado, volatilidade, maior queda, máxima e mínima, contra o Ibovespa ou o S&P 500 |
| `guardar_memoria` | `fact`, `category` | Grava um fato duradouro sobre o usuário; embedding e substituição seguem em segundo plano |
| `buscar_memorias` | `search_fact` | Fatos e trechos de conversas anteriores relacionados, por busca híbrida |
| `ver_memoria` | `memory_id` | O conteúdo completo; numa conversa, as mensagens originais do turno |
| `esquecer_memoria` | `memory_id` | Marca a memória como esquecida, sem apagá-la |

✋ Pede a confirmação do usuário antes de rodar (veja [Confirmação das operações](#confirmação-das-operações)).

As ferramentas são registradas automaticamente: `TOOLS`, em `src/agent/tools/definition.py` (mercado) e em `src/agent/tools/portfolio.py` (carteira e watchlist), varre o próprio módulo com `inspect` e recolhe todo objeto `BaseTool`; `src/agent/tools/registry.py` junta as duas listas. Para adicionar uma ferramenta, basta declará-la com `@tool` num desses arquivos. Se ela gravar dados, acrescente o nome a `APPROVAL_REQUIRED`, em `portfolio.py`.

---

## Requisitos

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** para gerenciar o ambiente e as dependências
- Uma **chave de API** de um provedor compatível com a API da OpenAI
- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** para rodar o Postgres e o Redis locais (no Windows, sobre o WSL2)

Não é preciso Node nem qualquer passo de build: o front-end é HTML, CSS e JavaScript puros, servidos direto pelo FastAPI.

### Dependências

Declaradas em `pyproject.toml` e resolvidas pelo `uv`:

| Pacote | Papel |
|---|---|
| `langgraph` | Orquestra o ciclo ReAct do agente |
| `langchain[openai]` | Cliente do modelo e definição das ferramentas |
| `yfinance` | Fonte dos dados de mercado |
| `pandas` | Tratamento das séries que o `yfinance` devolve |
| `fastapi` + `uvicorn` | Servidor HTTP e streaming SSE |
| `psycopg` + `psycopg-pool` | Driver e pool de conexões do Postgres |
| `langgraph-checkpoint-postgres` | Checkpoints do grafo no Postgres |
| `redis` | Cache dos dados de mercado e streams retomáveis |
| `bcrypt` | Hash das senhas |
| `httpx` | Chamadas ao modelo de decisão e à busca de notícias |
| `dotenv` | Carrega as credenciais do `.env` |

---

## Instalação

```bash
git clone <url-do-repositorio>
cd graham
uv sync
```

### Variáveis de ambiente

Crie um arquivo `.env` na raiz do projeto:

```dotenv
MODEL_PROVIDER_BASE_URL=https://ai-gateway.vercel.sh/v1
MODEL_PROVIDER_API_KEY=sua-chave-aqui
DATABASE_URL=postgresql://graham:graham@127.0.0.1:5432/graham?connect_timeout=10
REDIS_URL=redis://127.0.0.1:6379/0
```

`MODEL_PROVIDER_BASE_URL` precisa apontar para um endpoint compatível com a API de *chat completions* da OpenAI. Sem ela, o `ChatOpenAI` cai no padrão (`api.openai.com`) e a chave do seu provedor é rejeitada com `401`.

`DATABASE_URL` aponta para o Postgres do `compose.yaml`. Use `127.0.0.1`, não `localhost`: no Windows, `localhost` resolve primeiro para o IPv6 (`::1`), onde a porta não está publicada, e a conexão assíncrona do psycopg fica presa nesse endereço até o tempo limite em vez de passar para o IPv4. O `connect_timeout` faz qualquer falha de conexão aparecer em 10 segundos, em vez de travar.

### Banco de dados e Redis

```bash
docker compose up -d        # sobe o Postgres 18 com pgvector e o Redis
docker compose ps           # espere o status "healthy"
uv run db/migrate.py        # aplica as migrations pendentes
```

As migrations são arquivos SQL numerados em `db/migrations/`, aplicados em ordem e registrados em `public.schema_migrations`. A `0006_auth.sql` transforma o usuário anônimo de antes da autenticação na conta `user@email.com`, senha `graham`, com todos os dados dele; num banco novo nenhuma conta é criada, e a primeira se cria na tela de entrada. As tabelas dos checkpoints ficam de fora: o `AsyncPostgresSaver` as cria no schema `langgraph` quando o servidor sobe. Com alguma migration pendente, o servidor se recusa a subir e diz qual falta, em vez de falhar no meio do uso.

O Redis não guarda nada em disco: tudo nele é cache ou stream com TTL. Reiniciá-lo só custa refazer consultas à Yahoo e encerrar os turnos que estavam em andamento. Para espiá-lo, `docker compose exec redis redis-cli` abre um terminal (`KEYS graham:*` lista as chaves).

Para explorar o banco, `docker compose exec db psql -U graham` abre um terminal SQL (`\dn` lista os schemas, `\q` sai). `docker compose down` desliga o banco e mantém os dados; `docker compose down -v` os apaga.

### Configuração do modelo

O modelo e seus parâmetros ficam em `src/agent/config/settings.toml`, separados das credenciais:

```toml
[llm]
model = "deepseek/deepseek-v4-flash"
temperature = 0.2
timeout = 60

[embedding]
model = "perplexity/pplx-embed-v1-0.6b"
timeout = 20

[decision]
model = "typesafe-ai/jev"
timeout = 15

[memory]
profile_limit = 20
supersede_candidates = 5
supersede_probability = 0.5
```

O embedding e o modelo de decisão usam o mesmo gateway e a mesma chave do modelo de chat; o Jev responde pelo endpoint `/evaluate`, não pela API de chat. O `pplx-embed-v1-0.6b` devolve vetores INT8 de 1.024 dimensões, que a coluna `halfvec(1024)` guarda sem perda; trocar de modelo exige uma coluna com a dimensão nova e recalcular os embeddings (a coluna `embedding_model` diz quais estão desatualizados).

O modelo escolhido precisa suportar **tool calling** e **streaming** — sem os dois, o agente não consegue consultar dados nem responder progressivamente.

As instruções do agente ficam em `src/agent/instructions/system_prompt.md`, em Markdown, carregadas na inicialização.

---

## Como rodar

### Interface web

```bash
uv run uvicorn src.server.app:app --reload
```

Abra **http://127.0.0.1:8000** e entre com a sua conta (ou crie uma). O `--reload` reinicia o servidor a cada mudança em arquivo Python; alterações em CSS e JavaScript pedem apenas um *hard refresh* no navegador (`Ctrl+Shift+R`).

No Windows, o `--reload` é também o que faz o servidor funcionar: sem ele, o uvicorn usa o `ProactorEventLoop`, que o psycopg assíncrono não aceita, e o servidor se recusa a subir com uma mensagem dizendo isso.

### Linha de comando

```bash
uv run main.py
```

Um REPL simples, útil para testar o agente sem o navegador no caminho. Digite `sair` para encerrar. Ele não usa o banco: a conversa vive na memória do processo.

Ambos precisam ser executados a partir da **raiz do projeto** — os imports `src.*` são resolvidos em relação ao diretório de trabalho.

---

## Arquitetura

```
main.py                      REPL de linha de comando
compose.yaml                 Postgres 18 com pgvector, para desenvolvimento
db/
├── migrate.py               Aplica as migrations pendentes
└── migrations/              Schemas core, agent e langgraph, em SQL
src/
├── agent/
│   ├── config/
│   │   ├── model.py         Vincula as ferramentas ao modelo
│   │   ├── settings.py      Lê as configurações e cria o modelo puro, sem ferramentas
│   │   └── settings.toml    Modelo, embedding, decisão e memória
│   ├── decision.py          Perguntas tipadas ao modelo de decisão (Jev)
│   ├── instructions/
│   │   ├── __init__.py      Carrega o prompt como SystemMessage
│   │   └── system_prompt.md Instruções do agente
│   ├── memory/
│   │   ├── embeddings.py    Embeddings pelo gateway do provedor
│   │   └── processing.py    Embedding, substituição, indexação de turnos e backfill
│   ├── runtime/
│   │   ├── context.py       O que as ferramentas recebem do servidor: usuário, pool e perfil
│   │   └── state_graph.py   O grafo, o nó de aprovação e a função que o compila
│   └── tools/
│       ├── analysis.py      Proventos (de um ativo ou da carteira) e desempenho
│       ├── definition.py    As ferramentas de mercado e o registro automático
│       ├── memory.py        As ferramentas de memória
│       ├── portfolio.py     As ferramentas de carteira e watchlist
│       ├── registry.py      Junta as ferramentas e as que pedem confirmação
│       └── schemas/
│           ├── analysis.py  Schemas de entrada de proventos e desempenho
│           ├── input.py     Schemas de entrada (validam o que o modelo envia)
│           ├── memory.py    Schemas de entrada da memória
│           ├── portfolio.py Schemas de entrada da carteira e da watchlist
│           └── output.py    Schemas de saída (normalizam o que a Yahoo devolve)
├── server/
│   ├── app.py               FastAPI: conversas, SSE, cartões de ticker
│   ├── auth.py              Entrada, saída e criação de conta; a sessão de cada requisição
│   ├── recorder.py          Grava as mensagens de um turno conforme o grafo as produz
│   ├── streams.py           Turnos em segundo plano, gravados em Redis Streams retomáveis
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js           Cliente SSE, Markdown, histórico, ações e cartões de confirmação
└── storage/
    ├── accounts.py          Contas e sessões
    ├── cache.py             Cliente do Redis e cache dos dados de mercado
    ├── database.py          Pool de conexões
    ├── conversations.py     Consultas sobre threads e mensagens
    ├── history.py           Converte o caminho da thread no histórico do modelo
    ├── memories.py          Memórias: gravação, busca híbrida, substituição e esquecimento
    └── portfolio.py         Livro de operações, preço médio e watchlist
```

### O grafo do agente

Um ciclo ReAct com uma parada para confirmação, em `src/agent/runtime/state_graph.py`:

```mermaid
graph LR
    START([START]) --> agent
    agent{{agent — chama o modelo}} -->|sem tool call| END([END])
    agent -->|só consultas| tools[tools — executa as ferramentas]
    agent -->|alguma operação| approval[approval — espera o usuário]
    approval -->|aprovadas| tools
    approval -->|todas canceladas| agent
    tools --> agent
```

O estado é uma única chave `messages`, com o reducer `add_messages` do LangGraph cuidando de acumular o histórico. Se a última mensagem do modelo não traz `tool_calls`, o turno termina; se traz só consultas, elas rodam direto; se alguma grava dados, o grafo passa antes pelo nó `approval`.

As ferramentas recebem o usuário e o pool de conexões pelo **contexto da execução** (`AgentContext`, lido via `ToolRuntime`), que o modelo não vê e que não entra nos checkpoints. O REPL roda sem contexto, e as ferramentas de carteira respondem que só funcionam na interface web.

### Confirmação das operações

As ferramentas que gravam dados não rodam sem o usuário. Quando o modelo pede uma delas, o nó `approval` chama `interrupt()`, e o grafo para com o estado salvo no checkpoint do turno. A interface mostra um cartão por operação, com os valores que o agente propôs em campos editáveis e os botões **Confirmar** e **Cancelar**. Quando todas as operações do passo estão decididas, as decisões vão para `/api/approvals`, que as valida com o mesmo schema da ferramenta e retoma o grafo com `Command(resume=...)`.

- **A pausa fica num nó próprio, não dentro da ferramenta.** Ao retomar, o LangGraph roda de novo o nó que pausou, do começo. Num nó sem efeito colateral, repetir não muda nada; dentro de uma ferramenta, outras ferramentas do mesmo passo rodariam duas vezes.
- **Campos de lista são fechados.** A moeda do preço e a operação da watchlist aparecem como uma lista com busca (digitar "dolar" ou "USD" filtra), sem texto livre. As opções e os rótulos vêm do schema da ferramenta (`enum` e `x-labels`), o mesmo que o modelo vê e que o servidor usa para validar; a moeda só aceita as que têm câmbio na Yahoo com o dólar e com o real.
- **O ativo não se edita no cartão.** O ticker aparece fixo no cabeçalho, e o servidor ignora qualquer ticker diferente do proposto. Um ativo errado não é um valor a ajustar, e sim outra operação: o usuário cancela e pede a correção ao agente.
- **Só as aprovadas chegam às ferramentas.** O `ToolNode` executa todas as tool calls da última mensagem do modelo; por isso o nó de aprovação despacha uma tarefa por operação aprovada, via `Send`. As canceladas recebem uma resposta "o usuário cancelou", e o modelo explica.
- **A correção do usuário chega ao modelo.** O resultado da ferramenta traz `user_edits`, com o valor proposto e o aprovado. Sem isso, o modelo vê um valor diferente do que o usuário disse e conclui que errou.
- **A mensagem da pausa guarda o pedido e a decisão** (`payload.approval`), lado a lado. A mensagem do modelo fica com os valores aprovados, que são os que o histórico entrega dali em diante.
- **Uma pergunta nova no lugar da resposta ao cartão** encerra a confirmação como `interrupted`, sem fazer as operações. Depois de um dia, os checkpoints do turno somem e a confirmação expira (`410`).

### Carteira e watchlist

A carteira é um **livro de operações** (`core.portfolio_trades`): cada compra e cada venda é uma linha que nunca muda. A posição de cada ativo sai da aplicação das operações em ordem de data, pelo **preço médio**, o critério da Receita e da B3: uma compra recalcula a média ponderada, e uma venda reduz a quantidade sem mexer nela. Uma venda que deixaria a posição negativa em qualquer data é recusada. O preço fica na **moeda em que o usuário pagou** (`price_currency`), que pode ser diferente da moeda em que a Yahoo cota o ativo (`quote_currency`): Bitcoin comprado em reais é `BTC-USD` com preço em BRL. O custo fica nessa moeda, e só o valor atual é convertido, pelo câmbio do momento da consulta (`USDBRL=X`), então nenhum câmbio histórico é necessário. Cada ativo usa uma só moeda de pagamento, para o preço médio não misturar moedas. Os totais são por moeda de pagamento.

Na interface, a consulta à carteira aparece como as outras consultas, no aviso recolhível; ao abrir, as posições, os totais por moeda e as operações vêm em tabela, acima do JSON. Cada ferramenta pode ganhar uma vista assim em `TOOL_VIEWS`, no `app.js`.

A watchlist (`core.watchlist`) guarda o ativo, a operação pretendida (`compra`, `venda` ou `short`), o preço alvo e, opcionalmente, a quantidade, que transforma o acompanhamento num plano. O mesmo ativo pode aparecer mais de uma vez, com operações ou alvos diferentes.

### Memória de longo prazo

O agente guarda fatos duradouros sobre o usuário em `agent.memories`, em quatro categorias que ele mesmo escolhe: `perfil` (risco, horizonte, objetivos), `preferencia` (como quer as respostas), `interesse` (setores e temas, sem preço alvo, que é da watchlist) e `episodio` (acontecimentos, com a data). Uma quinta, `conversa`, é do sistema: cada turno concluído vira memória, com o título da conversa, a pergunta, as consultas feitas e a resposta final, para ser reencontrado depois.

- **Perfil e preferências estão sempre no contexto.** No início de cada turno, os ativos entram num bloco "O que você sabe sobre o usuário" do system prompt, via `AgentContext.profile`. O resto (interesses, episódios, conversas) é buscado sob demanda, com `buscar_memorias`.
- **Gravação imediata, resto em segundo plano.** `guardar_memoria` grava na hora e responde. O embedding e a checagem de substituição rodam depois, em `src/agent/memory/processing.py`; se o servidor cair no meio, a subida seguinte completa os embeddings que faltaram. A busca lexical já encontra a memória antes disso.
- **Substituição automática.** Ao guardar, o embedding ordena as 5 memórias ativas mais parecidas com a nova, de qualquer categoria menos `conversa`. Elas vão juntas ao modelo de decisão [Jev](https://vercel.com/ai-gateway/models/jev) (`src/agent/decision.py`), numa requisição só, com uma pergunta booleana por candidata: a memória nova torna esta dispensável? As que passam de 0,5 de probabilidade ganham `superseded_by_id` e saem da busca e do contexto. O cosseno sozinho não decidiria: na calibração, "conservador → arrojado" ficou em 0,61 e "bancos x energia", em 0,60, enquanto o Jev deu 0,72–0,94 aos pares do mesmo assunto e 0,03–0,08 aos diferentes, em cerca de 0,4 s. A pergunta é "dispensável", e não "mesmo assunto", para que um fato composto não perca a parte que continua valendo; o agente também é instruído a guardar um fato por memória. Se o Jev não responder, nada é substituído.
- **Esquecer não apaga.** `esquecer_memoria` marca `is_forgotten`, com data e a mensagem que pediu. Substituída quer dizer que o fato mudou; esquecida, que a memória estava errada ou o usuário pediu. Só a segunda é um sinal de erro de quem gerou a memória, e serve de rótulo para melhorar a geração no futuro.
- **Proveniência.** A ferramenta não conhece o id da nossa linha da mensagem que a chamou; o `TurnRecorder`, sim, e é ele quem liga a memória a essa mensagem (`agent.memory_sources`) e registra quem pediu o esquecimento. Uma memória `conversa` aponta para a pergunta e a resposta do turno.
- **Regeneração.** Quando uma resposta é regerada, a memória `conversa` da versão anterior é substituída pela nova.
- **Busca híbrida.** `agent.search_memories` combina a busca por embedding e a lexical (`tsvector` em português, com o sufixo do ticker separado) por Reciprocal Rank Fusion: o lexical acerta tickers e nomes exatos; o semântico, paráfrases.

### Autenticação

O usuário entra com e-mail e senha, e tudo o que é dele (conversas, memórias, carteira, watchlist) aponta para `core.users`. Sem sessão, a interface mostra só a tela de entrada, e as rotas respondem `401`.

- **Sessão guardada no servidor.** O cookie `graham_session` (`HttpOnly`, `SameSite=Lax`) leva um token aleatório; `core.sessions` guarda só o SHA-256 dele, e uma cópia do banco não serve para entrar. Sair apaga a sessão, que deixa de valer na hora. Ela dura 30 dias, e as vencidas são apagadas de hora em hora.
- **Senhas com bcrypt**, custo 12, calculado fora do event loop. Na criação de conta, a senha precisa de 8 caracteres; acima de 72 bytes, o bcrypt a truncaria, e ela é recusada.
- **Sem revelar quem tem conta no login.** E-mail inexistente e senha errada dão a mesma resposta, no mesmo tempo: um hash é conferido mesmo sem conta.
- **Força bruta.** Dez senhas erradas para o mesmo e-mail bloqueiam o login dele por 15 minutos (contador no Redis).
- **Fora do escopo, por decisão:** verificação de e-mail e recuperação de senha.

### Conversas no banco

O histórico da conversa vive nas tabelas do schema `agent`, e não no checkpointer. As mensagens formam uma **árvore**: cada uma aponta para a anterior (`parent_id`), e a thread guarda a última do caminho ativo (`head_message_id`).

- **Continuar** acrescenta uma pergunta embaixo da `head`.
- **Regerar** cria uma nova resposta como irmã da anterior, pendurada na mesma pergunta. A resposta antiga continua gravada, fora do caminho.
- **Bifurcar** cria uma thread cuja `head` é a mensagem escolhida. Nada é copiado: o caminho do fork sobe pelos `parent_id` até a thread de origem.

**Apagar é esconder.** `DELETE /api/threads/{id}` grava `deleted_at`, e a conversa some da lista, da busca e do acesso. As mensagens ficam, porque uma bifurcação sobe pelos `parent_id` até elas. As memórias `conversa` dos turnos dela, que são só o índice de busca desses turnos, saem de vez, e o agente não a reencontra mais; os fatos sobre o usuário guardados naquela conversa continuam. A busca de conversas ignora caixa e acentos (`unaccent`).

`agent.thread_path` devolve o caminho ativo em ordem, e é dele que sai o histórico entregue ao modelo a cada turno. Respostas interrompidas ou com erro ficam fora desse histórico, assim como pedidos de ferramenta que nunca receberam resposta, que os provedores recusam.

Cada mensagem tem um estado: `streaming` enquanto é gerada, `awaiting_approval` enquanto o turno espera a confirmação de uma operação, depois `completed`, `interrupted` (o servidor parou no meio do turno ou a confirmação foi abandonada) ou `failed`. Quando o servidor sobe, o que ficou em `streaming` vira `interrupted`.

### Streams retomáveis

Um turno não depende da conexão do navegador. O servidor roda o turno em segundo plano e grava cada evento SSE num **Redis Stream**; a resposta HTTP só lê desse stream. Se a conexão cair (a página recarregou, a rede piscou), o turno continua até o fim e é gravado inteiro.

- **Recarregar a página no meio de uma resposta:** `GET /api/threads/{id}` devolve o histórico até a mensagem de onde o turno parte e o `active_stream`. A interface redesenha o resto lendo o stream do começo e continua ao vivo.
- **A conexão cair sem recarregar:** cada evento traz o id do Redis no campo `id:` do SSE. A interface reconecta em `GET /api/streams/{id}?after=<último id>` e recebe só o que faltou.
- **Trocar de conversa no meio de uma resposta:** a interface só larga a leitura do stream; o turno segue no servidor. A aba de conversas marca a conversa como "respondendo" e, ao voltar a ela, a resposta é retomada como numa recarga.
- **Um turno por conversa:** enquanto há um em andamento, outra pergunta, regeneração ou confirmação na mesma conversa recebe `409`. Conversas diferentes respondem ao mesmo tempo.
- **O servidor parar no meio:** na subida seguinte, a mensagem em geração vira `interrupted` no Postgres, e o stream recebe um `done` final, para quem estiver lendo saber que acabou.

Os streams duram 1h no Redis (`graham:stream:{id}`), assim como a reserva da conversa (`graham:thread:{id}:active`).

### Cache

| O quê | Chave | TTL | Observações |
|---|---|---|---|
| Notícias | `graham:market:noticias_acao:*`, `graham:market:noticias_tema:*` | 1h | Resultado vazio não entra no cache: pode ser a fonte fora do ar |
| Proventos de um ativo | `graham:market:proventos:*` | 24h | |
| Histórico de preços | `graham:market:historico:*` | 1h | |
| Busca de ticker e triagem por setor | `graham:market:buscar_*:*` | 24h | Mudam raramente |
| Cotação | | | **Sem cache:** muda a todo momento, e um preço velho é pior do que nenhum |

**Notícias pela busca da Yahoo.** Desde 2026, o feed de notícias por ticker da Yahoo responde 404, e o yfinance (até a 1.7.0) devolve a falha como uma lista vazia, igual a "não há notícias". O feed continua sendo a primeira tentativa; vazio, a ferramenta busca pelo nome da empresa, em algumas variações (`Petróleo Brasileiro S.A. - Petrobras` não encontra nada, `Petrobras` encontra), e fica só com as notícias marcadas com alguma listagem da empresa (a Petrobras aparece como `PBR` e `PBR-A`). Essas notícias não trazem resumo, e o resultado avisa o modelo para não ir além do título.

**Proventos da carteira.** Sem ticker, `proventos` cruza o livro de operações com as datas ex da Yahoo: em cada pagamento, conta a quantidade que o usuário tinha no fim do pregão anterior, então uma compra feita na própria data ex não entra. Os valores são brutos, por ação ou cota.

**O gráfico não passa pelo modelo.** `desempenho` usa o `response_format="content_and_artifact"` do LangChain: o modelo recebe só as métricas (cerca de 1.700 caracteres para três ativos), e a série de pontos vai no artefato da `ToolMessage`. O servidor manda o artefato à interface no evento `tool_end` e o guarda no `payload` da mensagem da ferramenta, para o gráfico voltar ao reabrir a conversa; o histórico entregue ao modelo continua sem ele.

As conversas ficam fora do cache de propósito. Ler o caminho de uma thread no Postgres custa cerca de 1 ms, nada perto dos segundos de um turno, quase todos à espera do modelo. Uma cópia no Redis ocuparia memória proporcional às conversas ativas e traria o risco de mostrar uma versão desatualizada, em troca de um ganho que não aparece. O cache que faz diferença para a conversa é o do provedor do modelo, que reaproveita o começo do prompt entre chamadas; como o histórico só cresce no fim, ele já se beneficia disso.

O cache de mercado falha aberto: se o Redis não responder, os dados vêm direto da Yahoo. Os streams, não: sem Redis, o servidor não sobe.

### Os checkpoints

O `AsyncPostgresSaver` continua ligado, mas como **estado de execução**, não como histórico. Cada turno roda numa thread própria do LangGraph, nomeada pelo id da primeira mensagem do assistente daquele turno, e recebe o histórico já montado a partir das nossas tabelas. Os checkpoints ficam guardados por **um dia**, para inspecionar como o grafo executou, e depois uma tarefa de hora em hora os apaga.

Para ver os checkpoints de um turno, pegue o id da primeira mensagem do assistente e consulte `langgraph.checkpoints` com ele como `thread_id`. Os metadados de cada checkpoint trazem `graham_thread_id`, a conversa a que ele pertence.

### O caminho de uma pergunta

```mermaid
sequenceDiagram
    participant N as Navegador
    participant S as FastAPI
    participant G as Grafo
    participant Y as Yahoo Finance

    N->>S: POST /api/chat
    S->>G: astream_events(...)
    G-->>S: on_chat_model_stream
    S-->>N: event token
    G->>Y: consulta via ferramenta
    S-->>N: event tool_start
    Y-->>G: dados
    S-->>N: event tool_end
    G-->>S: on_chat_model_stream
    S-->>N: event token
    S-->>N: event ticker
    S-->>N: event done
```

O streaming vem de `astream_events(version="v2")`. Vale notar que **nenhum callback precisou ser registrado**: toda ferramenta LangChain já emite `on_tool_start`/`on_tool_end` por conta própria, e o `astream_events` apenas pendura um ouvinte que desce por toda a árvore de execução.

### Eventos SSE

| Evento | Payload | Uso na interface |
|---|---|---|
| `stream` | `{id}` | Primeiro evento: o stream do turno, para reconectar se a conexão cair |
| `thread` | `{id, title}` | Guarda o id da conversa (criada na primeira pergunta) |
| `thinking` | `{state: "start", at}` ou `{state: "end", ms}` | A linha "pensando", com o tempo desde `at`; o total vai para o "pensou por" do turno. O tempo é o intervalo entre o início da chamada ao modelo e a primeira saída dele: o raciocínio em si não é lido |
| `token` | `{text}` | Texto da resposta, pedaço a pedaço |
| `tool_start` | `{name, input}` | Abre o aviso "consultando…" e preenche *Argumentos* |
| `tool_end` | `{name, output}` | Fecha o aviso e preenche *Resultados* |
| `ticker` | cotação resumida | Um cartão de ticker |
| `approval` | `{message_id, requests}` | Os cartões de confirmação, com título, valores e schema de cada operação |
| `operation` | `{tool_call_id, status, message}` | O resultado de uma operação confirmada, no cartão dela |
| `error` | `{message}` | Aviso de falha na conversa |
| `done` | `{message_id, state}` | Fim do fluxo; a mensagem que fecha o turno recebe as ações de regerar e bifurcar |

### Rotas

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/auth/signup` | Recebe `{email, password}`, cria a conta e já entra |
| `POST` | `/api/auth/login` | Recebe `{email, password}` e grava o cookie de sessão |
| `POST` | `/api/auth/logout` | Apaga a sessão |
| `GET` | `/api/auth/me` | O e-mail da sessão, ou `401` |
| `POST` | `/api/chat` | Recebe `{message, thread_id?}` e devolve `text/event-stream`; sem `thread_id`, cria a conversa |
| `POST` | `/api/regenerate` | Recebe `{thread_id, message_id}` e transmite uma nova resposta para aquele turno |
| `POST` | `/api/approvals` | Recebe `{thread_id, message_id, decisions}` e transmite a continuação do turno pausado |
| `POST` | `/api/threads/{id}/fork` | Recebe `{message_id}` e devolve a nova conversa |
| `GET` | `/api/threads` | As conversas do usuário (até 100), da atividade mais recente à mais antiga, com o status `streaming` ou `awaiting_approval`; com `?q=`, só as que têm o texto no título ou nas mensagens, com o trecho encontrado |
| `PATCH` | `/api/threads/{id}` | Recebe `{title}` e renomeia a conversa |
| `DELETE` | `/api/threads/{id}` | Apaga a conversa; `409` se houver resposta em andamento |
| `GET` | `/api/threads/{id}` | O caminho ativo da conversa, agrupado em turnos |
| `GET` | `/api/streams/{id}` | Reconecta a um turno: os eventos depois de `?after=`, ou todos |
| `GET` | `/api/health` | Confirma que o grafo compilou e lista seus nós |
| `GET` | `/` | A interface |
| `GET` | `/static/*` | CSS e JavaScript |

### Os cartões de ticker

Ao final de cada resposta, os tickers citados viram cartões. A lista é o cruzamento de duas condições: o ticker passou por alguma ferramenta (logo, existe) **e** foi de fato mencionado no texto da resposta.

Citado por extenso (`BBAS3.SA`), o ticker sempre conta. Citado só pela base (`BBAS3`), vale uma listagem dela: a busca por empresa devolve também as de outras bolsas (`BBAS3.BA`, em Buenos Aires, cotada em peso), e o cartão seria de um ativo de que o agente não falou. Fica a que o agente consultou, senão a da B3, senão a primeira da busca.

Quando o agente já consultou `cotacao_atual_acao`, a cotação completa vem de graça no próprio `on_tool_end` — nenhuma consulta é repetida. Só os tickers que apareceram por outro caminho são buscados, em paralelo e depois que a resposta terminou de ser transmitida. O teto é de 8 cartões por resposta.

Os cartões não são gravados: ao reabrir uma conversa, as respostas e as consultas voltam, mas os cartões não.

---

## Decisões que valem conhecer

**Ferramentas vinculadas na definição do modelo.** `LLM` em `config/model.py` já é o resultado de `.bind_tools(TOOLS)`, porque o agente sempre dispõe do mesmo conjunto. O efeito colateral é que `LLM` não é mais um `BaseChatModel`, e sim um binding — algo a lembrar se um dia for preciso passá-lo a uma API que exija o modelo puro.

**Nós assíncronos são obrigatórios.** `call_model` usa `await LLM.ainvoke(...)`. Um `invoke()` síncrono roda numa thread e perde a propagação dos callbacks: os eventos `on_chat_model_stream` simplesmente não chegam, e o streaming morre silenciosamente.

**`NaN` não é JSON.** A Yahoo devolve `NaN` onde o dado não se aplica (o BTC-USD não tem fechamento anterior). Como `NaN` é um `float` válido em Python mas não existe no JSON, ele é convertido em `None` já na origem, no helper `_safe`, e há uma segunda rede em `_json_safe`, na serialização dos eventos SSE.

**O front-end não tem dependências.** O Markdown das respostas é renderizado por uma função de ~40 linhas em `app.js`, em vez de uma biblioteca de CDN. Tudo é escapado antes de virar HTML, então nada que o modelo ou a Yahoo devolvam pode injetar markup.
