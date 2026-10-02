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
| `buscar_ticker_por_empresa` | `company_name`, `count` | Tickers correspondentes a um nome de empresa, com bolsa, setor e indústria |
| `buscar_tickers_por_industria` | `industry`, `count`, `region` | Principais empresas de um dos 145 subsetores da classificação Yahoo |
| `ver_carteira` | `ticker_name?`, `currency?`, `include_trades?` | Posições com preço médio, total investido, valor atual e resultado, totais por moeda e resultado das vendas |
| `ver_watchlist` | `ticker_name?` | Entradas da watchlist com a cotação atual, a distância até o alvo e se ele foi atingido |
| `registrar_compra` ✋ | `ticker_name`, `quantity`, `unit_price`, `traded_on`, `currency?` | A operação gravada e a posição nova |
| `registrar_venda` ✋ | `ticker_name`, `quantity`, `unit_price`, `traded_on`, `currency?` | A operação gravada e a posição nova; recusa vender mais do que havia na data |
| `adicionar_watchlist` ✋ | `ticker_name`, `operation`, `target_price`, `quantity?` | A entrada criada |
| `remover_watchlist` ✋ | `ticker_name`, `operation`, `target_price?` | A entrada removida |

✋ Pede a confirmação do usuário antes de rodar (veja [Confirmação das operações](#confirmação-das-operações)).

As ferramentas são registradas automaticamente: `TOOLS`, em `src/agent/tools/definition.py` (mercado) e em `src/agent/tools/portfolio.py` (carteira e watchlist), varre o próprio módulo com `inspect` e recolhe todo objeto `BaseTool`; `src/agent/tools/registry.py` junta as duas listas. Para adicionar uma ferramenta, basta declará-la com `@tool` num desses arquivos. Se ela gravar dados, acrescente o nome a `APPROVAL_REQUIRED`, em `portfolio.py`.

---

## Requisitos

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** para gerenciar o ambiente e as dependências
- Uma **chave de API** de um provedor compatível com a API da OpenAI
- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** para rodar o Postgres local (no Windows, sobre o WSL2)

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
SESSION_SECRET=uma-sequencia-aleatoria-longa
```

`MODEL_PROVIDER_BASE_URL` precisa apontar para um endpoint compatível com a API de *chat completions* da OpenAI. Sem ela, o `ChatOpenAI` cai no padrão (`api.openai.com`) e a chave do seu provedor é rejeitada com `401`.

`DATABASE_URL` aponta para o Postgres do `compose.yaml`. Use `127.0.0.1`, não `localhost`: no Windows, `localhost` resolve primeiro para o IPv6 (`::1`), onde a porta não está publicada, e a conexão assíncrona do psycopg fica presa nesse endereço até o tempo limite em vez de passar para o IPv4. O `connect_timeout` faz qualquer falha de conexão aparecer em 10 segundos, em vez de travar. `SESSION_SECRET` assina o cookie que identifica o usuário anônimo; gere um com `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"`. Trocá-lo invalida os cookies existentes, e cada navegador passa a ser um usuário novo.

### Banco de dados

```bash
docker compose up -d        # sobe o Postgres 18 com pgvector
docker compose ps           # espere o status "healthy"
uv run db/migrate.py        # aplica as migrations pendentes
```

As migrations são arquivos SQL numerados em `db/migrations/`, aplicados em ordem e registrados em `public.schema_migrations`. As tabelas dos checkpoints ficam de fora: o `AsyncPostgresSaver` as cria no schema `langgraph` quando o servidor sobe.

Para explorar o banco, `docker compose exec db psql -U graham` abre um terminal SQL (`\dn` lista os schemas, `\q` sai). `docker compose down` desliga o banco e mantém os dados; `docker compose down -v` os apaga.

### Configuração do modelo

O modelo e seus parâmetros ficam em `src/agent/config/settings.toml`, separados das credenciais:

```toml
[llm]
model = "deepseek/deepseek-v4-flash"
temperature = 0.2
timeout = 60
```

O modelo escolhido precisa suportar **tool calling** e **streaming** — sem os dois, o agente não consegue consultar dados nem responder progressivamente.

As instruções do agente ficam em `src/agent/instructions/system_prompt.md`, em Markdown, carregadas na inicialização.

---

## Como rodar

### Interface web

```bash
uv run uvicorn src.server.app:app --reload
```

Abra **http://127.0.0.1:8000**. O `--reload` reinicia o servidor a cada mudança em arquivo Python; alterações em CSS e JavaScript pedem apenas um *hard refresh* no navegador (`Ctrl+Shift+R`).

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
│   │   ├── model.py         Instancia o LLM e vincula as ferramentas
│   │   └── settings.toml    Modelo, temperatura, timeout
│   ├── instructions/
│   │   ├── __init__.py      Carrega o prompt como SystemMessage
│   │   └── system_prompt.md Instruções do agente
│   ├── runtime/
│   │   ├── context.py       O que as ferramentas recebem do servidor: usuário e pool
│   │   └── state_graph.py   O grafo, o nó de aprovação e a função que o compila
│   └── tools/
│       ├── definition.py    As ferramentas de mercado e o registro automático
│       ├── portfolio.py     As ferramentas de carteira e watchlist
│       ├── registry.py      Junta as ferramentas e as que pedem confirmação
│       └── schemas/
│           ├── input.py     Schemas de entrada (validam o que o modelo envia)
│           ├── portfolio.py Schemas de entrada da carteira e da watchlist
│           └── output.py    Schemas de saída (normalizam o que a Yahoo devolve)
├── server/
│   ├── app.py               FastAPI: sessão, conversas, SSE, cartões de ticker
│   ├── recorder.py          Grava as mensagens de um turno conforme o grafo as produz
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js           Cliente SSE, Markdown, histórico, ações e cartões de confirmação
└── storage/
    ├── database.py          Pool de conexões
    ├── conversations.py     Consultas sobre usuários, threads e mensagens
    ├── history.py           Converte o caminho da thread no histórico do modelo
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
- **O ativo não se edita no cartão.** O ticker aparece fixo no cabeçalho, e o servidor ignora qualquer ticker diferente do proposto. Um ativo errado não é um valor a ajustar, e sim outra operação: o usuário cancela e pede a correção ao agente.
- **Só as aprovadas chegam às ferramentas.** O `ToolNode` executa todas as tool calls da última mensagem do modelo; por isso o nó de aprovação despacha uma tarefa por operação aprovada, via `Send`. As canceladas recebem uma resposta "o usuário cancelou", e o modelo explica.
- **A correção do usuário chega ao modelo.** O resultado da ferramenta traz `user_edits`, com o valor proposto e o aprovado. Sem isso, o modelo vê um valor diferente do que o usuário disse e conclui que errou.
- **A mensagem da pausa guarda o pedido e a decisão** (`payload.approval`), lado a lado. A mensagem do modelo fica com os valores aprovados, que são os que o histórico entrega dali em diante.
- **Uma pergunta nova no lugar da resposta ao cartão** encerra a confirmação como `interrupted`, sem fazer as operações. Depois de um dia, os checkpoints do turno somem e a confirmação expira (`410`).

### Carteira e watchlist

A carteira é um **livro de operações** (`core.portfolio_trades`): cada compra e cada venda é uma linha que nunca muda. A posição de cada ativo sai da aplicação das operações em ordem de data, pelo **preço médio**, o critério da Receita e da B3: uma compra recalcula a média ponderada, e uma venda reduz a quantidade sem mexer nela. Uma venda que deixaria a posição negativa em qualquer data é recusada. O preço fica na **moeda em que o usuário pagou** (`price_currency`), que pode ser diferente da moeda em que a Yahoo cota o ativo (`quote_currency`): Bitcoin comprado em reais é `BTC-USD` com preço em BRL. O custo fica nessa moeda, e só o valor atual é convertido, pelo câmbio do momento da consulta (`USDBRL=X`), então nenhum câmbio histórico é necessário. Cada ativo usa uma só moeda de pagamento, para o preço médio não misturar moedas. Os totais são por moeda de pagamento.

Na interface, a consulta à carteira aparece como as outras consultas, no aviso recolhível; ao abrir, as posições, os totais por moeda e as operações vêm em tabela, acima do JSON. Cada ferramenta pode ganhar uma vista assim em `TOOL_VIEWS`, no `app.js`.

A watchlist (`core.watchlist`) guarda o ativo, a operação pretendida (`compra`, `venda` ou `short`), o preço alvo e, opcionalmente, a quantidade, que transforma o acompanhamento num plano. O mesmo ativo pode aparecer mais de uma vez, com operações ou alvos diferentes.

### Conversas no banco

O histórico da conversa vive nas tabelas do schema `agent`, e não no checkpointer. As mensagens formam uma **árvore**: cada uma aponta para a anterior (`parent_id`), e a thread guarda a última do caminho ativo (`head_message_id`).

- **Continuar** acrescenta uma pergunta embaixo da `head`.
- **Regerar** cria uma nova resposta como irmã da anterior, pendurada na mesma pergunta. A resposta antiga continua gravada, fora do caminho.
- **Bifurcar** cria uma thread cuja `head` é a mensagem escolhida. Nada é copiado: o caminho do fork sobe pelos `parent_id` até a thread de origem.

`agent.thread_path` devolve o caminho ativo em ordem, e é dele que sai o histórico entregue ao modelo a cada turno. Respostas interrompidas ou com erro ficam fora desse histórico, assim como pedidos de ferramenta que nunca receberam resposta, que os provedores recusam.

Cada mensagem tem um estado: `streaming` enquanto é gerada, `awaiting_approval` enquanto o turno espera a confirmação de uma operação, depois `completed`, `interrupted` (o cliente desconectou, o servidor caiu ou a confirmação foi abandonada) ou `failed`. Quando o servidor sobe, o que ficou em `streaming` vira `interrupted`.

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
| `thread` | `{id, title}` | Guarda o id da conversa (criada na primeira pergunta) |
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
| `POST` | `/api/session` | Cria o usuário anônimo na primeira visita e grava o cookie assinado |
| `POST` | `/api/chat` | Recebe `{message, thread_id?}` e devolve `text/event-stream`; sem `thread_id`, cria a conversa |
| `POST` | `/api/regenerate` | Recebe `{thread_id, message_id}` e transmite uma nova resposta para aquele turno |
| `POST` | `/api/approvals` | Recebe `{thread_id, message_id, decisions}` e transmite a continuação do turno pausado |
| `POST` | `/api/threads/{id}/fork` | Recebe `{message_id}` e devolve a nova conversa |
| `GET` | `/api/threads/{id}` | O caminho ativo da conversa, agrupado em turnos |
| `GET` | `/api/health` | Confirma que o grafo compilou e lista seus nós |
| `GET` | `/` | A interface |
| `GET` | `/static/*` | CSS e JavaScript |

### Os cartões de ticker

Ao final de cada resposta, os tickers citados viram cartões. A lista é o cruzamento de duas condições: o ticker passou por alguma ferramenta (logo, existe) **e** foi de fato mencionado no texto da resposta.

Quando o agente já consultou `cotacao_atual_acao`, a cotação completa vem de graça no próprio `on_tool_end` — nenhuma consulta é repetida. Só os tickers que apareceram por outro caminho são buscados, em paralelo e depois que a resposta terminou de ser transmitida. O teto é de 8 cartões por resposta.

Os cartões não são gravados: ao reabrir uma conversa, as respostas e as consultas voltam, mas os cartões não.

---

## Decisões que valem conhecer

**Ferramentas vinculadas na definição do modelo.** `LLM` em `config/model.py` já é o resultado de `.bind_tools(TOOLS)`, porque o agente sempre dispõe do mesmo conjunto. O efeito colateral é que `LLM` não é mais um `BaseChatModel`, e sim um binding — algo a lembrar se um dia for preciso passá-lo a uma API que exija o modelo puro.

**Nós assíncronos são obrigatórios.** `call_model` usa `await LLM.ainvoke(...)`. Um `invoke()` síncrono roda numa thread e perde a propagação dos callbacks: os eventos `on_chat_model_stream` simplesmente não chegam, e o streaming morre silenciosamente.

**`NaN` não é JSON.** A Yahoo devolve `NaN` onde o dado não se aplica (o BTC-USD não tem fechamento anterior). Como `NaN` é um `float` válido em Python mas não existe no JSON, ele é convertido em `None` já na origem, no helper `_safe`, e há uma segunda rede em `_json_safe`, na serialização dos eventos SSE.

**O front-end não tem dependências.** O Markdown das respostas é renderizado por uma função de ~40 linhas em `app.js`, em vez de uma biblioteca de CDN. Tudo é escapado antes de virar HTML, então nada que o modelo ou a Yahoo devolvam pode injetar markup.
