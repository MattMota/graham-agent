# Graham Agent

[![CI](https://github.com/MattMota/graham-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/MattMota/graham-agent/actions/workflows/ci.yml)

> Seu corretor de confiança.

Um agente de investimentos pessoal para a B3 e as bolsas americanas. Ele responde sobre o mercado com dados da Yahoo Finance, guarda a carteira, a watchlist e a memória do usuário, e compara a carteira com a alocação que o usuário definiu. Toda gravação passa por um cartão de confirmação, e as ferramentas ficam num servidor MCP que outros agentes da máquina também usam.

Projeto de estudo: as cotações vêm com atraso e nada aqui é recomendação de investimento. Roda só na máquina do usuário, por decisão ([ADR 0001](docs/adr/0001-graham-roda-so-localmente.md)).

![Uma compra parada no cartão de confirmação, com o ativo travado e os valores editáveis](docs/images/confirmacao.png)
*Toda gravação para num cartão: o usuário confirma, corrige ou cancela antes de algo ir para a carteira.*

![O enquadramento da carteira contra a alocação-alvo, por classe e por ativo](docs/images/enquadramento.png)
*A carteira contra a alocação-alvo, em reais. O IVVB11 conta como exterior por escolha do usuário, e não como ETF.*

> **In English.** A personal investment agent (in Portuguese) for the Brazilian and US markets.
>
> - **MCP as the platform**: 18 tools with schemas and annotations, reference resources and skills (SEP-2640), served over authenticated Streamable HTTP with read and write scopes. The agent itself is just another client.
> - **Human in the loop**: a hand-written LangGraph graph stops every write at an editable confirmation card, waits on a Postgres checkpoint and resumes with the user's edits.
> - **Resilient streaming**: AG-UI events go through Redis Streams, so a run survives a dropped connection and the UI resumes where it stopped.
> - **Long-term memory**: hybrid search (pgvector and full text, fused by rank) and fact replacement decided by a calibrated decision model.
> - **Real domain logic**: average-cost ledger, dividends by ex-date, earnings calendar, target allocation with drift check and rebalancing.
> - **Quality and operations**: unit, graph (scripted model), full-server integration and opt-in model evals; CI on GitHub Actions; per-run latency, token and tool-error metrics; retries with backoff; optional LangSmith traces. Decisions, including what was left out, are in [`docs/adr/`](docs/adr/).

---

## Destaques

- **O servidor MCP como plataforma.** As 18 ferramentas, os resources de referência e as skills ficam num servidor MCP autenticado por chaves com escopo de leitura ou escrita ([`src/mcp_server/`](src/mcp_server/)). O próprio agente o consome como qualquer cliente, com um token interno por turno; agentes locais (Claude Code, Codex, Cursor) usam as mesmas ferramentas. → [O servidor MCP](docs/arquitetura/mcp.md)
- **Aprovação humana de verdade.** O grafo do LangGraph é escrito à mão: `agent`, `approval` e `tools`. Toda gravação para num cartão em que o usuário confirma, corrige ou cancela. O grafo espera no checkpoint do Postgres, retoma só as aprovadas e devolve as correções ao modelo ([`state_graph.py`](src/agent/runtime/state_graph.py)). → [O agente](docs/arquitetura/agente.md)
- **Streaming que sobrevive à conexão.** A interface fala AG-UI. Cada execução roda em segundo plano e grava os eventos num Redis Stream, então recarregar a página ou perder a rede não interrompe a resposta. O servidor, e não o cliente, é a fonte da verdade do histórico. → [A interface e o AG-UI](docs/arquitetura/interface.md)
- **Memória de longo prazo.** Fatos sobre o usuário e turnos passados, com busca híbrida (pgvector e texto, por Reciprocal Rank Fusion). A substituição de um fato desatualizado é decidida por um modelo de decisão, calibrado contra o cosseno. → [A memória](docs/arquitetura/memoria.md)
- **Domínio financeiro com regras próprias.** Livro de operações com preço médio, proventos pela data ex, agenda de resultados, e alocação-alvo com enquadramento e rebalanceamento por aporte. Também trata as particularidades da Yahoo, como datas no fuso errado e FIIs marcados como ações. → [Carteira e dados de mercado](docs/arquitetura/carteira-e-mercado.md)
- **Qualidade medida.** Testes em quatro camadas: unidade; grafo com um modelo roteirizado; o servidor inteiro contra Postgres e Redis; evals com o modelo de verdade. A CI roda no GitHub Actions, e os traces na LangSmith são opcionais, agrupados por conversa. → [Testes](docs/desenvolvimento.md#testes)
- **Operação.** Cada execução grava latência, tokens e erros de ferramenta, resumidos em `/api/metrics`; as chamadas ao modelo, à Yahoo e ao Google News tentam de novo as falhas passageiras, e cada dependência tem um comportamento definido quando cai. Os traces na LangSmith são opcionais, agrupados por conversa. → [Operação](docs/arquitetura/operacao.md)
- **Decisões registradas.** Os [ADRs](docs/adr/) dizem o que ficou de fora e por quê: OAuth e A2A, Deep Agents e multi-agente, frameworks de eval com juiz, carteiras-modelo. O [glossário](CONTEXT.md) fixa o vocabulário do domínio.

## Arquitetura

```mermaid
flowchart LR
    UI["Interface web<br/>HTML, CSS e JS sem build"] -- "AG-UI (SSE)" --> API["FastAPI<br/>/api/agent"]
    API <--> RS[("Redis<br/>streams e cache")]
    API --> G["Grafo LangGraph<br/>agent · approval · tools"]
    G --> LLM["Provedor do modelo"]
    G -- "token interno por turno" --> MCP["Servidor MCP /mcp<br/>ferramentas · resources · skills"]
    EXT["Agentes locais<br/>Claude Code, Codex, Cursor"] -- "chave de acesso" --> MCP
    MCP --> Y["Yahoo Finance<br/>Google News"]
    MCP --> PG[("Postgres<br/>carteira, alocação, contas")]
    G --> PG
    API --> PG
    G -. opcional .-> LS["LangSmith"]
```

Python 3.13, LangGraph, FastAPI, o SDK oficial do MCP, Postgres 18 com pgvector e Redis. A interface é HTML, CSS e JavaScript puros, sem build. Detalhes em [docs/arquitetura](docs/arquitetura/).

## O que ele faz

Você pergunta em linguagem natural: *"Quanto vale BBAS3 hoje?"*, *"Por que a Vale caiu?"*, *"Minha carteira está enquadrada? Tenho R$ 5 mil para aportar."*. O agente escolhe as consultas, executa e explica. A resposta chega token a token, e carteira, proventos, desempenho, agenda e alocação aparecem em tabelas e gráficos.

| Domínio | Ferramentas |
|---|---|
| Mercado | `cotacao_atual_acao`, `noticias_acao`, `noticias_tema`, `buscar_ticker_por_empresa`, `buscar_tickers_por_industria` |
| Análise | `proventos`, `desempenho`, `agenda_eventos` |
| Carteira e watchlist | `ver_carteira`, `ver_watchlist`, `registrar_compra` ✋, `registrar_venda` ✋, `adicionar_watchlist` ✋, `remover_watchlist` ✋ |
| Alocação | `ver_enquadramento`, `sugerir_rebalanceamento`, `definir_alocacao` ✋, `definir_classe_ativo` ✋ |
| Memória (só do Graham) | `guardar_memoria`, `buscar_memorias`, `ver_memoria`, `esquecer_memoria` |
| Skills | `ler_skill`, com 5 roteiros: analisar um ativo, explicar um movimento, revisar e rebalancear a carteira, registrar uma operação |

✋ Passa pelo cartão de confirmação. Argumentos e retornos de cada uma: [O servidor MCP](docs/arquitetura/mcp.md#ferramentas).

## Como rodar

Precisa de Python 3.13, [uv](https://docs.astral.sh/uv/), Docker e uma chave de um provedor compatível com a API da OpenAI.

```bash
cp .env.example .env                          # e preencha MODEL_PROVIDER_API_KEY
docker compose --profile app up -d --build    # Postgres, Redis e o Graham em http://127.0.0.1:8000
```

Para desenvolver, com recarga a cada mudança:

```bash
uv sync
docker compose up -d                          # só o Postgres e o Redis
uv run db/migrate.py
uv run uvicorn src.server.app:app --reload
```

Configuração do modelo, traces na LangSmith, o REPL e o MCP Inspector: [Desenvolvimento](docs/desenvolvimento.md).

## Testes

```bash
uv run pytest                     # unidade e grafo, sem serviços
TEST_DATABASE_URL=postgresql://graham:graham@127.0.0.1:5432/graham_test \
TEST_REDIS_URL=redis://127.0.0.1:6379/1 \
uv run pytest                     # mais a integração, com o Postgres e o Redis do compose
uv run pytest -m eval             # evals com o modelo de verdade (custam tokens)
```

O que cada camada cobre, e como o não determinismo fica isolado: [Testes](docs/desenvolvimento.md#testes).

## Estrutura

```
src/
├── agent/          O grafo, o prompt, a memória e o cliente do MCP
├── mcp_server/     O servidor MCP: registro das ferramentas, resources e skills
├── tools/          As ferramentas, sem LangChain, e o catálogo delas
├── server/         FastAPI: AG-UI, streams, conversas, contas, chaves e a interface
└── storage/        Postgres e Redis
db/migrations/      O schema, em SQL numerado
tests/              Unidade, grafo, integração e evals
docs/               Arquitetura, desenvolvimento, features e ADRs
```

## Documentação

| Documento | Para quê |
|---|---|
| [docs/arquitetura/](docs/arquitetura/) | Como cada parte funciona, com a árvore completa do código |
| [docs/desenvolvimento.md](docs/desenvolvimento.md) | Instalar, configurar, rodar e testar |
| [docs/FEATURES.md](docs/FEATURES.md) | O que existe, o que está pendente e o que ficou fora do escopo |
| [docs/adr/](docs/adr/) | As decisões, em especial o que ficou de fora e por quê |
| [CONTEXT.md](CONTEXT.md) | O vocabulário do domínio |

---

© 2026 Matheus Mota. Todos os direitos reservados. O código está público para leitura e avaliação, sem licença de uso.
