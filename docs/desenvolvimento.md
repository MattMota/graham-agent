# Desenvolvimento

Como instalar, configurar, rodar e testar o Graham. A visão geral está no [README](../README.md).

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

## Instalação

```bash
git clone <url-do-repositorio>
cd graham
uv sync
```

### Variáveis de ambiente

Copie o `.env.example` para `.env`, na raiz do projeto, e preencha a chave do modelo:

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

## Testes

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
| `tests/unit/` | Preço médio e resultado realizado, proventos pela data ex, datas da agenda (UTC e fuso da bolsa), schemas de entrada, escolha dos cartões de ticker, classe de ativo e a conta do enquadramento e do rebalanceamento | Nada |
| `tests/graph/` | O grafo com um modelo roteirizado: consulta direta, pausa antes de gravar, valores corrigidos no cartão, cancelamento, resposta com consulta e operações juntas, REPL sem contexto | Nada |
| `tests/integration/` | O servidor inteiro numa thread: o MCP com chaves de leitura e de escrita e a carteira isolada por dono; um turno pelo AG-UI com ferramenta, texto, cartões, snapshot, confirmação editada, cancelada e abandonada; a memória `conversa` do turno; alocação-alvo, enquadramento, rebalanceamento com aporte e classe escolhida por ativo | Postgres e Redis |
| `tests/evals/` | O modelo configurado escolhe a primeira ferramenta certa em 13 perguntas, cada uma 3 vezes, com 2 acertos exigidos | O `.env` com a chave do modelo |

- **O não determinismo fica isolado.** O grafo, a confirmação e o AG-UI são testados com um modelo roteirizado (`tests/fakes.py`), que fixa as respostas e as transmite em pedaços como um provedor; o que se testa é o que o Graham faz com elas. O modelo de verdade só entra nos evals, que medem uma taxa de acerto em vez de exigir a mesma resposta.
- **Nada externo é chamado.** Na integração, a cotação, as datas de eventos e os embeddings vêm de tabelas fixas, e o modelo segue o roteiro; a Yahoo e o provedor nunca são chamados. O `tests/conftest.py` anula o `.env` antes de qualquer import: sem Redis de uso, sem traces na LangSmith, sem chave do modelo.
- **O banco de uso fica intocado.** O banco da integração é recriado a cada sessão e precisa terminar em `_test`; o Redis precisa ser um banco diferente do 0.

A CI (`.github/workflows/ci.yml`) roda o ruff e a suíte, menos os evals, a cada push na `main` e em cada pull request, com o Postgres (pgvector) e o Redis como serviços.
