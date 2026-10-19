# Graham Agent

> Seu corretor de confiança.

Um agente conversacional que responde perguntas sobre ações, empresas e setores consultando a Yahoo Finance em tempo real. O nome é uma homenagem a Benjamin Graham, e a interface segue essa ideia: papel off-white, tipografia serifada e respostas que se leem com calma, sem o ruído de um terminal de operações.

O projeto é de estudo. As cotações vêm com atraso e nada aqui é recomendação de investimento.

> **In English.** Graham is a personal investment agent for the Brazilian (B3) and US markets, in Portuguese. It answers market questions with live Yahoo Finance data and keeps the user's portfolio, watchlist and long-term memory. It also checks the portfolio against a target allocation the user sets, and suggests how to rebalance it. Every write (a trade, a watchlist change, the target allocation) stops at a confirmation card the user can edit before anything is stored. Under the hood: a hand-written LangGraph ReAct graph with a human-in-the-loop node and Postgres checkpoints. The tools live on an authenticated MCP server, with resources and skills (SEP-2640), that other local agents can use too. The UI talks to the agent over AG-UI, with resumable streams on Redis, and traces are optional in LangSmith. Tests come in four layers: unit, graph with a scripted model, full-server integration, and opt-in model evals. CI runs on GitHub Actions. It runs only on the user's machine, by design. The decisions behind what was left out are in [`docs/adr/`](docs/adr/), the domain vocabulary in [`CONTEXT.md`](CONTEXT.md), and the feature map in [`docs/FEATURES.md`](docs/FEATURES.md).

---

## O que ele faz

Você pergunta em linguagem natural — *"Quanto vale BBAS3 hoje?"*, *"Notícias da Petrobras"*, *"Compare ouro e Bitcoin"* — e o agente decide sozinho quais consultas precisa fazer, executa e explica o resultado.

Além do mercado, ele cuida da sua **carteira** e da **watchlist** (cada operação passa por um cartão de confirmação), calcula os **proventos** recebidos, compara o **desempenho** de ativos contra o índice, monta a **agenda** dos próximos resultados e datas ex, compara a carteira com a **alocação-alvo** que você definiu e sugere como **rebalanceá-la** com um aporte, e guarda uma **memória** do seu perfil e das conversas anteriores.

A resposta chega **token a token**, com os dados aparecendo conforme são buscados. Ao final, os tickers citados viram cartões de cotação recolhíveis, e cada consulta feita pode ser aberta para inspeção (argumentos enviados e JSON devolvido).

### Ferramentas disponíveis ao agente

As de mercado, análise, carteira e watchlist ficam no [servidor MCP](#servidor-mcp) do Graham, que outros agentes também podem usar; as de memória são só do Graham.

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
| `agenda_eventos` | `tickers?`, `days` | Próximos resultados, datas ex e pagamentos, em ordem de data; sem tickers, os da carteira e da watchlist, com a origem e a quantidade |
| `ver_enquadramento` | | Valor e peso de cada classe de ativo em reais, contra a alocação-alvo: desvio e se está dentro, acima ou abaixo da banda; e o peso de cada ativo |
| `sugerir_rebalanceamento` | `contribution`, `allow_sales` | Ordens por ativo que levariam a carteira ao alvo, usando primeiro o aporte; o que sobra e as classes sem ativo, com candidatos da watchlist. Não registra nada |
| `definir_alocacao` ✋ | `acoes_br`, `fundos`, `etfs`, `exterior`, `cripto`, `tolerance` | A alocação-alvo gravada: o peso de cada classe, somando 100%, e a banda de tolerância |
| `definir_classe_ativo` ✋ | `ticker_name`, `asset_class` | A classe em que o ativo passa a contar na alocação, no lugar da automática; `fora` o tira da conta, `automatica` desfaz a escolha |
| `guardar_memoria` | `fact`, `category` | Grava um fato duradouro sobre o usuário; embedding e substituição seguem em segundo plano |
| `buscar_memorias` | `search_fact` | Fatos e trechos de conversas anteriores relacionados, por busca híbrida |
| `ver_memoria` | `memory_id` | O conteúdo completo; numa conversa, as mensagens originais do turno |
| `esquecer_memoria` | `memory_id` | Marca a memória como esquecida, sem apagá-la |
| `ler_skill` | `name`, `file?` | O texto de uma skill do servidor MCP (um roteiro para tarefa recorrente) ou de um arquivo de apoio dela |

✋ Pede a confirmação do usuário antes de rodar (veja [Confirmação das operações](#confirmação-das-operações)).

Para adicionar uma ferramenta ao MCP, escreva a função em `src/tools/` (recebe um `ToolContext` e os argumentos), o modelo de entrada no módulo do mesmo domínio em `src/tools/schemas/` e uma entrada em `CATALOG`, em `src/tools/catalog.py`, com o nome, a descrição e o escopo (`READ` ou `WRITE`). O servidor a publica e o Graham passa a usá-la na subida seguinte; se ela gravar dados (`WRITE`), o grafo pede a confirmação do usuário antes. As de memória continuam como ferramentas LangChain, em `src/agent/tools/memory.py`.

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
| `ag-ui-protocol` | Tipos dos eventos e da entrada do AG-UI, o protocolo entre o agente e as interfaces |
| `psycopg` + `psycopg-pool` | Driver e pool de conexões do Postgres |
| `langgraph-checkpoint-postgres` | Checkpoints do grafo no Postgres |
| `redis` | Cache dos dados de mercado e streams retomáveis |
| `bcrypt` | Hash das senhas |
| `httpx` | Chamadas ao modelo de decisão e à busca de notícias |
| `mcp` | SDK oficial do Model Context Protocol: o servidor MCP e o cliente que o Graham usa |
| `dotenv` | Carrega as credenciais do `.env` |

Para desenvolvimento, no grupo `dev`, que o `uv sync` também instala: `pytest` e `pytest-asyncio` para os [testes](#testes), e `ruff` para o lint.

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
PUBLIC_URL=http://127.0.0.1:8000
```

`MODEL_PROVIDER_BASE_URL` precisa apontar para um endpoint compatível com a API de *chat completions* da OpenAI. Sem ela, o `ChatOpenAI` cai no padrão (`api.openai.com`) e a chave do seu provedor é rejeitada com `401`.

`DATABASE_URL` aponta para o Postgres do `compose.yaml`. Use `127.0.0.1`, não `localhost`: no Windows, `localhost` resolve primeiro para o IPv6 (`::1`), onde a porta não está publicada, e a conexão assíncrona do psycopg fica presa nesse endereço até o tempo limite em vez de passar para o IPv4. O `connect_timeout` faz qualquer falha de conexão aparecer em 10 segundos, em vez de travar.

`PUBLIC_URL` é o endereço pelo qual o servidor é alcançado, sem barra no fim: dele saem a URL do servidor MCP (`{PUBLIC_URL}/mcp`), os metadados de autorização e os hosts aceitos. O padrão é `http://127.0.0.1:8000`; mude-o se rodar em outra porta ou atrás de um domínio. O Graham chama o próprio MCP por esse endereço; para usar outro caminho interno (atrás de um proxy, por exemplo), defina `MCP_INTERNAL_URL`.

#### Traces na LangSmith (opcional)

Para ver cada turno do agente na [LangSmith](https://smith.langchain.com) (chamadas ao modelo, ferramentas do MCP e o nó de aprovação), acrescente ao `.env`:

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=graham
```

O SDK já vem com o LangChain; nada no código liga ou desliga o tracing além dessas variáveis. Os turnos de uma conversa aparecem agrupados na aba *Threads* do projeto, pelo id da conversa. Os embeddings e o modelo de decisão da memória chamam o provedor direto pelo `httpx` e ficam de fora.

Sem cartão cadastrado, o plano gratuito aceita 5.000 traces por mês e recusa os seguintes, sem cobrar; com cartão, o excedente é cobrado. Cada turno é um trace (retomar depois de uma confirmação abre outro). Os traces vão para os servidores da LangSmith com as perguntas, as respostas e os resultados das ferramentas, inclusive a carteira e o perfil do usuário; com `LANGSMITH_TRACING=false`, nada sai da máquina.

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

### Tudo no Docker

```bash
docker compose --profile app up -d --build
```

Sobe o Postgres, o Redis e o Graham, que aplica as migrations pendentes e atende em **http://127.0.0.1:8000**. A chave do modelo (e os traces opcionais) vêm do `.env`; os endereços do banco e do Redis, do `compose.yaml`. Fica num perfil à parte para não ocupar a porta de quem desenvolve com o `--reload`: o `docker compose up -d` comum continua subindo só o Postgres e o Redis.

### Linha de comando

```bash
uv run main.py
```

Um REPL simples, útil para testar o agente sem o navegador no caminho. Digite `sair` para encerrar. Ele não usa o banco: a conversa vive na memória do processo.

Ambos precisam ser executados a partir da **raiz do projeto** — os imports `src.*` são resolvidos em relação ao diretório de trabalho.

### Testes

```bash
uv run pytest                     # unidade e grafo; a integração é pulada sem as variáveis abaixo
TEST_DATABASE_URL=postgresql://graham:graham@127.0.0.1:5432/graham_test \
TEST_REDIS_URL=redis://127.0.0.1:6379/1 \
uv run pytest                     # tudo, com o Postgres e o Redis do compose
uv run pytest -m eval             # evals com o modelo de verdade (custam tokens)
uv run ruff check .
```

A suíte tem quatro camadas, da mais rápida à mais lenta:

| Pasta | O que cobre | Precisa de |
|---|---|---|
| `tests/unit/` | Preço médio e resultado realizado, proventos pela data ex, datas da agenda (UTC e fuso da bolsa), schemas de entrada, escolha dos cartões de ticker | Nada |
| `tests/graph/` | O grafo com um modelo roteirizado: consulta direta, pausa antes de gravar, valores corrigidos no cartão, cancelamento, resposta com consulta e operações juntas, REPL sem contexto | Nada |
| `tests/integration/` | O servidor inteiro numa thread: o MCP com chaves de leitura e de escrita e a carteira isolada por dono; um turno pelo AG-UI com ferramenta, texto, cartões, snapshot, confirmação editada, cancelada e abandonada; a memória `conversa` do turno | Postgres e Redis |
| `tests/evals/` | O modelo configurado escolhe a primeira ferramenta certa em 9 perguntas, cada uma 3 vezes, com 2 acertos exigidos | O `.env` com a chave do modelo |

- **O não determinismo fica isolado.** O grafo, a confirmação e o AG-UI são testados com um modelo roteirizado (`tests/fakes.py`), que fixa as respostas e as transmite em pedaços como um provedor; o que se testa é o que o Graham faz com elas. O modelo de verdade só entra nos evals, que medem uma taxa de acerto em vez de exigir a mesma resposta.
- **Nada externo é chamado.** Na integração, a cotação, as datas de eventos e os embeddings vêm de tabelas fixas, e o modelo segue o roteiro; a Yahoo e o provedor nunca são chamados. O `tests/conftest.py` anula o `.env` antes de qualquer import: sem Redis de uso, sem traces na LangSmith, sem chave do modelo.
- **O banco de uso fica intocado.** O banco da integração é recriado a cada sessão e precisa terminar em `_test`; o Redis precisa ser um banco diferente do 0.

A CI (`.github/workflows/ci.yml`) roda o ruff e a suíte, menos os evals, a cada push na `main` e em cada pull request, com o Postgres (pgvector) e o Redis como serviços.

---

## Arquitetura

```
main.py                      REPL de linha de comando
compose.yaml                 Postgres 18 com pgvector e Redis; no perfil app, o Graham
Dockerfile                   A imagem do Graham, que aplica as migrations ao subir
CONTEXT.md                   O vocabulário do domínio
docs/
├── FEATURES.md              O mapa das features: existentes, pendentes e fora do escopo
└── adr/                     As decisões, em especial o que ficou de fora e por quê
.github/workflows/ci.yml     Ruff e testes a cada push e pull request
db/
├── migrate.py               Aplica as migrations pendentes
└── migrations/              Schemas core, agent e langgraph, em SQL
scripts/
└── mcp_inspector.py         Abre o MCP Inspector conectado ao /mcp, com uma chave temporária
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
│   │   ├── context.py       O que as ferramentas recebem do servidor: usuário, pool, perfil e a conexão MCP
│   │   └── state_graph.py   O grafo, o nó de aprovação e a função que o compila
│   └── tools/
│       ├── memory.py        As ferramentas de memória, locais
│       ├── registry.py      As ferramentas do MCP e as locais, e as que pedem confirmação
│       ├── remote.py        As ferramentas do MCP vistas como ferramentas LangChain; a conexão do turno
│       ├── skills.py        O catálogo de skills do MCP no prompt e a ferramenta ler_skill
│       └── schemas/
│           └── memory.py    Schemas de entrada da memória
├── mcp_server/
│   ├── resources/           Material de referência do MCP: convenções e glossário (Markdown), fontes e catálogos
│   ├── skills/              Skills por grupo (analise, carteira); o padrão está no CLAUDE.md da pasta
│   ├── skills_extension.py  Serve as skills pela extensão SEP-2640 e como prompts
│   └── server.py            Servidor MCP: verificador de tokens e registro do catálogo
├── tools/                   As ferramentas publicadas pelo MCP, sem LangChain
│   ├── allocation.py        Classe de ativo, enquadramento e rebalanceamento
│   ├── analysis.py          Proventos (de um ativo ou da carteira), desempenho e agenda de eventos
│   ├── catalog.py           Nome, descrição, entrada, função e escopo de cada uma
│   ├── context.py           ToolContext (usuário e pool) e ToolFailure
│   ├── market.py            Cotação, notícias e buscas no yfinance e no Google News
│   ├── portfolio.py         Carteira e watchlist
│   └── schemas/             Um módulo por domínio, como as ferramentas
│       ├── allocation.py    Entrada da alocação-alvo e do rebalanceamento
│       ├── analysis.py      Entrada de proventos, desempenho e agenda
│       ├── common.py        Tipos usados por mais de um domínio (o ticker)
│       ├── market.py        Entrada e saída das ferramentas de mercado (a saída normaliza o que a Yahoo devolve)
│       └── portfolio.py     Entrada da carteira e da watchlist
├── server/
│   ├── app.py               FastAPI: subida, conversas (REST) e estáticos; monta o MCP em /mcp
│   ├── agent.py             As rotas do agente em AG-UI: executar, religar (connect) e retomar a leitura
│   ├── agui.py              O contrato AG-UI: entrada, snapshot da conversa e interrupções
│   ├── runs.py              Executa o grafo e traduz os eventos em AG-UI; cartões de ticker
│   ├── auth.py              Entrada, saída e criação de conta; a sessão de cada requisição
│   ├── keys.py              Chaves de acesso ao MCP e ao agente: criar, listar e revogar
│   ├── recorder.py          Grava as mensagens de um turno conforme o grafo as produz
│   ├── streams.py           Execuções em segundo plano, gravadas em Redis Streams retomáveis
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js           Cliente AG-UI, Markdown, histórico, ações e cartões de confirmação
└── storage/
    ├── accounts.py          Contas e sessões
    ├── allocation.py        Alocação-alvo do usuário
    ├── cache.py             Cliente do Redis e cache dos dados de mercado
    ├── database.py          Pool de conexões
    ├── conversations.py     Consultas sobre threads e mensagens
    ├── history.py           Converte o caminho da thread no histórico do modelo
    ├── memories.py          Memórias: gravação, busca híbrida, substituição e esquecimento
    ├── portfolio.py         Livro de operações, preço médio e watchlist
    └── tokens.py            Tokens de acesso: chaves e tokens internos
tests/
├── conftest.py              Anula o .env antes de qualquer import
├── fakes.py                 O modelo roteirizado
├── unit/                    Regras de domínio e funções puras
├── graph/                   O grafo e a confirmação, com o modelo roteirizado
├── integration/             O servidor inteiro, contra Postgres e Redis de teste
└── evals/                   O modelo de verdade escolhendo ferramentas
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

As ferramentas que gravam dados não rodam sem o usuário. Quando o modelo pede uma delas, o nó `approval` chama `interrupt()`, e o grafo para com o estado salvo no checkpoint do turno. A execução termina com uma interrupção do AG-UI por operação, e a interface mostra um cartão para cada uma, com os valores que o agente propôs em campos editáveis e os botões **Confirmar** e **Cancelar**. Quando todas as operações do passo estão decididas, as respostas vão no `resume` de uma execução nova, que as valida com o mesmo schema da ferramenta e retoma o grafo com `Command(resume=...)`.

- **A pausa fica num nó próprio, não dentro da ferramenta.** Ao retomar, o LangGraph roda de novo o nó que pausou, do começo. Num nó sem efeito colateral, repetir não muda nada; dentro de uma ferramenta, outras ferramentas do mesmo passo rodariam duas vezes.
- **Campos de lista são fechados.** A moeda do preço e a operação da watchlist aparecem como uma lista com busca (digitar "dolar" ou "USD" filtra), sem texto livre. As opções e os rótulos vêm do schema da ferramenta (`enum` e `x-labels`), o mesmo que o modelo vê e que o servidor usa para validar; a moeda só aceita as que têm câmbio na Yahoo com o dólar e com o real.
- **O ativo não se edita no cartão.** O ticker aparece fixo no cabeçalho, e o servidor ignora qualquer ticker diferente do proposto. Um ativo errado não é um valor a ajustar, e sim outra operação: o usuário cancela e pede a correção ao agente.
- **Só as aprovadas chegam às ferramentas.** O `ToolNode` executa todas as tool calls da última mensagem do modelo; por isso o nó de aprovação despacha uma tarefa por operação aprovada, via `Send`. As canceladas recebem uma resposta "o usuário cancelou", e o modelo explica.
- **A correção do usuário chega ao modelo.** O resultado da ferramenta traz `user_edits`, com o valor proposto e o aprovado. Sem isso, o modelo vê um valor diferente do que o usuário disse e conclui que errou.
- **A mensagem da pausa guarda o pedido e a decisão** (`payload.approval`), lado a lado. A mensagem do modelo fica com os valores aprovados, que são os que o histórico entrega dali em diante.
- **Uma pergunta nova no lugar da resposta ao cartão** encerra a confirmação como `interrupted`, sem fazer as operações. O AG-UI pede que ela vá junto, com as interrupções como `cancelled`; sem isso, a execução é recusada. Depois de um dia, os checkpoints do turno somem e a confirmação expira (`expiresAt` na interrupção, `RUN_ERROR` com `code: "expired"` ao responder).

### Carteira e watchlist

A carteira é um **livro de operações** (`core.portfolio_trades`): cada compra e cada venda é uma linha que nunca muda. A posição de cada ativo sai da aplicação das operações em ordem de data, pelo **preço médio**, o critério da Receita e da B3: uma compra recalcula a média ponderada, e uma venda reduz a quantidade sem mexer nela. Uma venda que deixaria a posição negativa em qualquer data é recusada. O preço fica na **moeda em que o usuário pagou** (`price_currency`), que pode ser diferente da moeda em que a Yahoo cota o ativo (`quote_currency`): Bitcoin comprado em reais é `BTC-USD` com preço em BRL. O custo fica nessa moeda, e só o valor atual é convertido, pelo câmbio do momento da consulta (`USDBRL=X`), então nenhum câmbio histórico é necessário. Cada ativo usa uma só moeda de pagamento, para o preço médio não misturar moedas. Os totais são por moeda de pagamento.

Na interface, a carteira, os proventos, o desempenho (com o gráfico) e a agenda de eventos ganham uma vista em tabela, que aparece depois da rodada de consultas e antes do texto da resposta; mais de uma vista no mesmo turno vem recolhida, cada uma sob um título. O JSON continua no detalhe da consulta. Cada ferramenta pode ganhar uma vista assim em `TOOL_VIEWS`, no `app.js`.

**Alocação-alvo, enquadramento e rebalanceamento.** O usuário define o peso que quer para cada classe de ativo (ações brasileiras, fundos listados, ETFs, exterior, cripto), somando 100%, e uma banda de tolerância; a definição passa pelo cartão de confirmação, como uma operação, e fica em `core.allocation_targets`. O Graham não traz carteiras-modelo nem decide os pesos a partir do perfil ([ADR 0004](docs/adr/0004-alocacao-alvo-definida-pelo-usuario.md)). A classe de cada ativo sai do tipo e do nome na Yahoo, que marca FIIs e ETFs da B3 como ações: o nome separa os fundos ("Imobiliário", "Fiagro") e os ETFs ("Classe de Índice"), e o código separa os BDRs (final 31 a 35 ou 39). A classe é a do instrumento, não a da exposição: o IVVB11 é um ETF, embora exponha ao S&P 500. Quando o usuário vê um ativo de outro jeito, ele escolhe a classe daquele ativo com `definir_classe_ativo`, que passa pelo cartão e vale mais que a automática, só para ele (`core.asset_class_overrides`); a tabela do enquadramento mostra se cada classe é automática ou escolha dele. Os pesos são medidos em reais, pelo câmbio de agora, a única conta do Graham que soma moedas. `ver_enquadramento` compara cada classe com o alvo; `sugerir_rebalanceamento` calcula as ordens: sem vendas, o aporte vai às classes abaixo do alvo na proporção do que falta a cada uma; com vendas, cada classe volta ao alvo. Dentro da classe, o valor se divide na proporção do que o usuário já tem, e as quantidades são arredondadas para baixo. A sugestão não grava nada; a skill `rebalancear-carteira` leva o agente a registrar cada ordem com `registrar_compra` ou `registrar_venda`, de novo com o cartão.

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

### Servidor MCP

As ferramentas de mercado, análise, carteira e watchlist vivem num servidor [MCP](https://modelcontextprotocol.io), em `{PUBLIC_URL}/mcp` (Streamable HTTP), montado na mesma app do servidor web. O próprio Graham o consome, e outros agentes podem se conectar a ele com uma chave de acesso.

- **Chaves de acesso.** Em *Conectar agentes*, no rodapé da aba de conversas, o usuário cria uma chave com nome, vê o valor uma única vez (com um exemplo de configuração para o Claude Code) e pode revogá-la. A chave nasce só de leitura; gravar na carteira e na watchlist exige marcar a permissão ao criá-la. O agente envia `Authorization: Bearer graham_...`; o banco guarda só o SHA-256 (`core.access_tokens`).
- **Escopos.** `graham:leitura` em toda chave, `graham:escrita` nas que podem gravar. As quatro ferramentas que gravam vêm anotadas como destrutivas, para o cliente pedir a confirmação dele; sem a permissão, a chamada é recusada com uma explicação.
- **O Graham pelo MCP.** A cada turno, o servidor emite um token interno do usuário (curto, apagado no fim do turno) e abre uma conexão MCP com ele, numa tarefa própria. O cookie da sessão nunca vai ao MCP. As operações que gravam continuam passando antes pelo cartão de confirmação; as correções feitas nele são anexadas ao resultado do lado do Graham.
- **Definições na subida.** O Graham lê nome, descrição e esquema de entrada das ferramentas do próprio servidor, em processo, ao subir (o HTTP ainda não atende nesse momento), e liga o modelo a elas ao compilar o grafo.
- **O gráfico à parte.** O `desempenho` devolve as métricas no texto e a série do gráfico em `structuredContent`, que vira o artefato da mensagem: a interface desenha, o modelo não gasta tokens com ela.
- **Autorização.** Sem token, `/mcp` responde `401` com `WWW-Authenticate` apontando para os metadados do recurso protegido (RFC 9728, em `/.well-known/oauth-protected-resource/mcp`). A autenticação é só por chaves de acesso: o Graham roda na máquina do usuário e não é publicado, então conectores que exigem OAuth e acesso pela internet, como os do claude.ai e do ChatGPT, ficam de fora. Agentes locais (Claude Code, Codex, Cursor) usam as chaves.
- **Resources de referência.** Além das ferramentas, o servidor publica o que um agente precisa saber para usá-las bem: `graham://convencoes` (códigos de ativos, moedas, percentuais, datas, notas, erros e escrita), `graham://glossario` (o sentido exato de cada termo dos resultados, como é calculado), `graham://fontes` (de onde vem cada dado e por quanto tempo fica em cache, tirado das próprias constantes do código), `graham://catalogo/industrias` (os 145 subsetores aceitos) e `graham://catalogo/moedas`. Só referência, nada do usuário: a carteira já é servida pelas ferramentas, e um resource com dados pessoais tende a entrar inteiro no contexto do agente cliente. O Graham lê as convenções do próprio MCP na subida e as põe no prompt, sem a seção de escrita (nele, quem confirma é o cartão).
- **Skills.** Roteiros para tarefas recorrentes (`analisar-ativo`, `explicar-movimento`, `revisar-carteira`, `registrar-operacao`), organizados por grupo em `src/mcp_server/skills/`. Saem de três formas: pela extensão de skills do MCP ([SEP-2640](https://modelcontextprotocol.io/seps/2640-skills-extension), `skills/list` e `skills/get` com o SHA-256 de cada arquivo, em `skill://<grupo>/<nome>/SKILL.md`), que só existe na versão 2026-07-28 do protocolo; como prompts de mesmo nome, com argumentos, para os clientes que ainda não falam a extensão; e no próprio Graham, que lista nome e descrição de cada uma no prompt e carrega o roteiro com `ler_skill` quando a tarefa pede. O SDK documenta um suporte de servidor a skills que ainda não saiu (a 2.3.0 é a última publicada); até lá, os dois métodos são implementados sobre o mecanismo genérico de extensões dele. Como criar uma skill, e o padrão de variantes por argumento, está no `CLAUDE.md` da pasta.
- **A memória fica de fora.** Guardar, buscar, ver e esquecer memórias continuam ferramentas locais do Graham: a memória é dele, e expô-la deixaria outro agente ler e alterar o que ele sabe do usuário.

No REPL, sem usuário, as ferramentas MCP rodam em processo: as de mercado funcionam, e as de carteira avisam que precisam de uma conta.

#### Inspecionar o servidor

Com o servidor no ar, o [MCP Inspector](https://github.com/modelcontextprotocol/inspector) abre já conectado ao `/mcp`, em nome de uma conta:

```bash
uv run scripts/mcp_inspector.py --email user@email.com             # interface web, só leitura
uv run scripts/mcp_inspector.py --email user@email.com --escrita   # permite as ferramentas que gravam
uv run scripts/mcp_inspector.py --email user@email.com -- --cli --method tools/list
```

O script cria uma chave temporária para a conta (só leitura, a não ser com `--escrita`), passa-a ao Inspector no cabeçalho `Authorization` e a revoga quando ele fecha; se o script cair antes, ela vence em 12 horas. Ele também pede ao Inspector a negociação automática da versão do protocolo (`--protocol-era auto`): na versão antiga, que o Inspector usaria por padrão, as skills não aparecem. Para conferir a conformidade delas com a SEP-2640: `-- --cli --method skills/list --verify`. O que vier depois de `--` vai direto ao Inspector. Precisa do Node (`npx`). Sem a chave, o Inspector tentaria o fluxo OAuth, que o servidor não oferece.

### AG-UI

A nossa interface e o agente conversam por [AG-UI](https://docs.ag-ui.com), o protocolo aberto entre agentes e interfaces, em `/api/agent`. Só ela usa essas rotas, com o cookie da sessão: o Graham Agent fica nesta plataforma. Para fora, há só o servidor MCP, com as ferramentas. A escolha é por um contrato padrão entre a tela e o agente (trocar um lado sem mexer no outro, usar componentes prontos e, depois, o A2UI por cima dele), não por capacidade: retomar a leitura de uma resposta, o tempo de pensamento e os cartões de ticker são do Graham, fora do protocolo. O AG-UI é um dos padrões que estão se consolidando (LangGraph, o Agent Framework da Microsoft, CopilotKit), não o único.

- **O servidor é a fonte da verdade do histórico.** O `threadId` é o id da conversa, e das `messages` de uma execução o servidor usa só a pergunta nova: a última, se for do usuário e o id dela ainda não estiver gravado. O resto que o cliente reenviar é ignorado. Com o cliente como fonte da verdade, ele poderia fabricar resultados de ferramenta, falas do agente ou confirmações de operação, e o Graham grava na carteira, depende da confirmação humana e forma memória a partir dos turnos. A API de *responses* da OpenAI (`previous_response_id`) segue o mesmo meio-termo.
- **Ids do cliente.** O cliente gera o `threadId` de uma conversa nova (o servidor a cria com ele), o `runId` de cada execução e o id da pergunta, que vira o id da linha no banco.
- **Regerar** é uma execução com `forwardedProps: {"graham": {"regenerate": "<id da resposta>"}}`, sem inferir nada comparando o histórico enviado. **Bifurcar continua REST**: só cria a conversa, e as execuções seguintes usam o novo `threadId`. Também ficam REST a lista, a busca, renomear e apagar conversas, as chaves e a conta.
- **Religar** (`POST /api/agent/connect`, como a rota `connect` do CopilotKit): uma execução que só ressincroniza (o `MESSAGES_SNAPSHOT` do caminho gravado e, se a conversa espera confirmação, o fim com as interrupções abertas) e, havendo uma execução em andamento, os eventos dela desde o começo. A interface redesenha toda conversa que abre assim.
- **Os extras do Graham vão em `metadata.graham`**, que o AG-UI deixa livre em todo evento e mensagem: o estado de cada resposta, o tempo de pensamento, o gráfico, o id da mensagem que fecha o turno, os campos travados do cartão. O fluxo básico (perguntar, receber a resposta, confirmar operações) é AG-UI padrão; regerar e os extras são do Graham. Ferramentas definidas pelo cliente (`tools`), contexto e estado compartilhado são ignorados.
- **Sem o adaptador pronto.** O `ag-ui-langgraph` passaria por cima do gravador no banco, da confirmação pelo nosso grafo e dos streams retomáveis, como o cliente MCP do LangChain passaria. Do pacote `ag-ui-protocol` vêm só os tipos.

### Conversas no banco

O histórico da conversa vive nas tabelas do schema `agent`, e não no checkpointer. As mensagens formam uma **árvore**: cada uma aponta para a anterior (`parent_id`), e a thread guarda a última do caminho ativo (`head_message_id`).

- **Continuar** acrescenta uma pergunta embaixo da `head`.
- **Regerar** cria uma nova resposta como irmã da anterior, pendurada na mesma pergunta. A resposta antiga continua gravada, fora do caminho.
- **Bifurcar** cria uma thread cuja `head` é a mensagem escolhida. Nada é copiado: o caminho do fork sobe pelos `parent_id` até a thread de origem.

**Apagar é esconder.** `DELETE /api/threads/{id}` grava `deleted_at`, e a conversa some da lista, da busca e do acesso. As mensagens ficam, porque uma bifurcação sobe pelos `parent_id` até elas. As memórias `conversa` dos turnos dela, que são só o índice de busca desses turnos, saem de vez, e o agente não a reencontra mais; os fatos sobre o usuário guardados naquela conversa continuam. A busca de conversas ignora caixa e acentos (`unaccent`).

`agent.thread_path` devolve o caminho ativo em ordem, e é dele que sai o histórico entregue ao modelo a cada turno. Respostas interrompidas ou com erro ficam fora desse histórico, assim como pedidos de ferramenta que nunca receberam resposta, que os provedores recusam.

Cada mensagem tem um estado: `streaming` enquanto é gerada, `awaiting_approval` enquanto o turno espera a confirmação de uma operação, depois `completed`, `interrupted` (o servidor parou no meio do turno ou a confirmação foi abandonada) ou `failed`. Quando o servidor sobe, o que ficou em `streaming` vira `interrupted`.

### Streams retomáveis

Uma execução não depende da conexão do cliente. O servidor roda a execução em segundo plano e grava cada evento AG-UI num **Redis Stream**, com o `runId` como id; a resposta HTTP só lê desse stream. Se a conexão cair (a página recarregou, a rede piscou), a execução continua até o fim e é gravada inteira. O AG-UI não define retomada (a especificação do transporte diz que um stream interrompido não pode ser reaberto); ela é do Graham, pelo padrão do SSE.

- **Recarregar a página no meio de uma resposta:** o `connect` devolve o snapshot até a mensagem de onde a execução parte e, em seguida, os eventos dela desde o começo. A interface redesenha o resto e continua ao vivo.
- **A conexão cair sem recarregar:** cada evento traz o id do Redis no campo `id:` do SSE. A interface reconecta em `GET /api/agent/runs/{runId}/events` com o cabeçalho `Last-Event-ID` (o que o `EventSource` manda sozinho) ou `?after=`, e recebe só o que faltou.
- **Trocar de conversa no meio de uma resposta:** a interface só larga a leitura do stream; o turno segue no servidor. A aba de conversas marca a conversa como "respondendo" e, ao voltar a ela, a resposta é retomada como numa recarga.
- **Uma execução por conversa:** enquanto há uma em andamento, outra pergunta, regeneração ou confirmação na mesma conversa recebe `409`, assim como um `runId` repetido. Conversas diferentes respondem ao mesmo tempo.
- **O servidor parar no meio:** na subida seguinte, a mensagem em geração vira `interrupted` no Postgres, e o stream recebe um `RUN_ERROR` com `code: "interrupted"`, para quem estiver lendo saber que acabou.

Os streams duram 1h no Redis (`graham:stream:{id}`), assim como a reserva da conversa (`graham:thread:{id}:active`).

### Cache

| O quê | Chave | TTL | Observações |
|---|---|---|---|
| Notícias | `graham:market:noticias_acao:*`, `graham:market:noticias_tema:*` | 1h | Resultado vazio não entra no cache: pode ser a fonte fora do ar |
| Proventos de um ativo | `graham:market:proventos:*` | 24h | |
| Datas de eventos | `graham:market:eventos:*` | 6h | Resultado, data ex e pagamento de um ativo; uma data ex pode ser anunciada para o dia seguinte |
| Histórico de preços | `graham:market:historico:*` | 1h | |
| Busca de ticker e triagem por setor | `graham:market:buscar_*:*` | 24h | Mudam raramente |
| Classe de ativo | `graham:market:classe:*` | 7 dias | O tipo e o nome de um ativo na Yahoo quase nunca mudam |
| Cotação | | | **Sem cache:** muda a todo momento, e um preço velho é pior do que nenhum |

**Notícias pela busca da Yahoo.** Desde 2026, o feed de notícias por ticker da Yahoo responde 404, e o yfinance (até a 1.7.0) devolve a falha como uma lista vazia, igual a "não há notícias". O feed continua sendo a primeira tentativa; vazio, a ferramenta busca pelo nome da empresa, em algumas variações (`Petróleo Brasileiro S.A. - Petrobras` não encontra nada, `Petrobras` encontra), e fica só com as notícias marcadas com alguma listagem da empresa (a Petrobras aparece como `PBR` e `PBR-A`). Essas notícias não trazem resumo, e o resultado avisa o modelo para não ir além do título.

**Proventos da carteira.** Sem ticker, `proventos` cruza o livro de operações com as datas ex da Yahoo: em cada pagamento, conta a quantidade que o usuário tinha no fim do pregão anterior, então uma compra feita na própria data ex não entra. Os valores são brutos, por ação ou cota.

**Datas de eventos pelo `info`.** A agenda e a próxima data ex de `proventos` vêm do `info` da Yahoo, não do `calendar`. O yfinance (até a 1.7.0) converte as datas do `calendar` pelo fuso da máquina, e a Yahoo grava as de proventos à meia-noite UTC: num servidor no Brasil, a data ex saía um dia antes (a da Apple caía num domingo). As de proventos são lidas em UTC; as de resultado, que são um horário, no fuso da bolsa. A Yahoo nem sempre tem o próximo resultado das empresas brasileiras (PETR4 e ITUB4 vêm sem, VALE3 e WEGE3 com), e a ferramenta lista esses ativos à parte, sem afirmar que não há evento.

**O gráfico não passa pelo modelo.** `desempenho` usa o `response_format="content_and_artifact"` do LangChain: o modelo recebe só as métricas (cerca de 1.700 caracteres para três ativos), e a série de pontos vai no artefato da `ToolMessage`. O servidor manda o artefato à interface no `metadata` do `TOOL_CALL_RESULT` e o guarda no `payload` da mensagem da ferramenta, para o gráfico voltar ao reabrir a conversa; o histórico entregue ao modelo continua sem ele.

As conversas ficam fora do cache de propósito. Ler o caminho de uma thread no Postgres custa cerca de 1 ms, nada perto dos segundos de um turno, quase todos à espera do modelo. Uma cópia no Redis ocuparia memória proporcional às conversas ativas e traria o risco de mostrar uma versão desatualizada, em troca de um ganho que não aparece. O cache que faz diferença para a conversa é o do provedor do modelo, que reaproveita o começo do prompt entre chamadas; como o histórico só cresce no fim, ele já se beneficia disso.

O cache de mercado falha aberto: se o Redis não responder, os dados vêm direto da Yahoo. Os streams, não: sem Redis, o servidor não sobe.

### Os checkpoints

O `AsyncPostgresSaver` continua ligado, mas como **estado de execução**, não como histórico. Cada turno roda numa thread própria do LangGraph, nomeada pelo id da primeira mensagem do assistente daquele turno, e recebe o histórico já montado a partir das nossas tabelas. Os checkpoints ficam guardados por **um dia**, para inspecionar como o grafo executou, e depois uma tarefa de hora em hora os apaga.

Para ver os checkpoints de um turno, pegue o id da primeira mensagem do assistente e consulte `langgraph.checkpoints` com ele como `thread_id`. Os metadados de cada checkpoint trazem a conversa a que ele pertence, em `graham_thread_id` e em `thread_id`. O segundo é o que a LangSmith usa para agrupar os turnos de uma conversa; sem ele, o LangGraph copiaria para os metadados o `thread_id` do turno, e cada pergunta viraria uma thread à parte.

### O caminho de uma pergunta

```mermaid
sequenceDiagram
    participant N as Navegador
    participant S as FastAPI
    participant G as Grafo
    participant Y as Yahoo Finance

    N->>S: POST /api/agent (RunAgentInput)
    S-->>N: RUN_STARTED
    S->>G: astream_events(...)
    G-->>S: on_chat_model_stream
    S-->>N: REASONING_START … REASONING_END
    S-->>N: TOOL_CALL_START, TOOL_CALL_ARGS, TOOL_CALL_END
    G->>Y: consulta via ferramenta do MCP
    Y-->>G: dados
    S-->>N: TOOL_CALL_RESULT
    G-->>S: on_chat_model_stream
    S-->>N: TEXT_MESSAGE_START, CONTENT…, END
    S-->>N: CUSTOM graham.tickers
    S-->>N: RUN_FINISHED
```

O streaming vem de `astream_events(version="v2")`. Vale notar que **nenhum callback precisou ser registrado**: toda ferramenta LangChain já emite `on_tool_start`/`on_tool_end` por conta própria, e o `astream_events` apenas pendura um ouvinte que desce por toda a árvore de execução.

### Eventos AG-UI

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

### Rotas

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

### Os cartões de ticker

Ao final de cada resposta, os tickers citados viram cartões. A lista é o cruzamento de duas condições: o ticker passou por alguma ferramenta (logo, existe) **e** foi de fato mencionado no texto da resposta.

Citado por extenso (`BBAS3.SA`), o ticker sempre conta. Citado só pela base (`BBAS3`), vale uma listagem dela: a busca por empresa devolve também as de outras bolsas (`BBAS3.BA`, em Buenos Aires, cotada em peso), e o cartão seria de um ativo de que o agente não falou. Fica a que o agente consultou, senão a da B3, senão a primeira da busca.

Quando o agente já consultou `cotacao_atual_acao`, a cotação completa vem de graça no próprio `on_tool_end` — nenhuma consulta é repetida. Só os tickers que apareceram por outro caminho são buscados, em paralelo e depois que a resposta terminou de ser transmitida. O teto é de 8 cartões por resposta.

Os cartões não são gravados: ao reabrir uma conversa, as respostas e as consultas voltam, mas os cartões não.

---

## Decisões que valem conhecer

As decisões de arquitetura e de escopo, em especial o que ficou de fora e por quê, estão em [`docs/adr/`](docs/adr/): o Graham só local ([0001](docs/adr/0001-graham-roda-so-localmente.md)), um agente só, sem Deep Agents nem multi-agente ([0002](docs/adr/0002-um-agente-so.md)), evals sem framework de juiz ([0003](docs/adr/0003-evals-sem-framework-de-juiz.md)) e a alocação-alvo definida pelo usuário ([0004](docs/adr/0004-alocacao-alvo-definida-pelo-usuario.md)). Abaixo, as de implementação.

**Ferramentas vinculadas ao compilar o grafo.** As ferramentas do MCP só são conhecidas na subida, ao listar o servidor, então `bind_model(tools)`, em `config/model.py`, liga o modelo a elas quando o grafo é compilado, e não na importação. O resultado é um binding, não um `BaseChatModel`; quem precisa do modelo puro (o processamento de memória, por exemplo) usa `chat_model()`, de `config/settings.py`.

**Nós assíncronos são obrigatórios.** O nó `agent` usa `await model.ainvoke(...)`. Um `invoke()` síncrono roda numa thread e perde a propagação dos callbacks: os eventos `on_chat_model_stream` simplesmente não chegam, e o streaming morre silenciosamente.

**`NaN` não é JSON.** A Yahoo devolve `NaN` onde o dado não se aplica (o BTC-USD não tem fechamento anterior). Como `NaN` é um `float` válido em Python mas não existe no JSON, ele é convertido em `None` já na origem, no helper `_safe`. Os eventos AG-UI são modelos Pydantic, que serializam `NaN` como `null`: uma segunda rede, sem código nosso.

**O front-end não tem dependências.** O Markdown das respostas é renderizado por uma função de ~40 linhas em `app.js`, em vez de uma biblioteca de CDN. Tudo é escapado antes de virar HTML, então nada que o modelo ou a Yahoo devolvam pode injetar markup.
