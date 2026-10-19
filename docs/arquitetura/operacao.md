# Operação: métricas, falhas e recuperação

O que o Graham mede de cada execução e o que ele faz quando uma dependência falha.

## Métricas por execução

Cada execução do agente (uma pergunta, a retomada depois de um cartão, uma regeneração) grava uma linha em `agent.run_metrics` ao terminar, no Postgres da máquina do usuário. Sem depender da LangSmith, que é opcional e mais detalhada, mas vai para a nuvem.

| Campo | O que mede |
|---|---|
| `outcome` | Como terminou: `completed`, `awaiting_approval`, `failed` ou `interrupted` |
| `duration_ms` | Do início ao fim da execução |
| `first_output_ms` | Do início à primeira saída do modelo (texto ou tool call): o que o usuário sente como espera |
| `model_calls` | Quantas vezes o modelo foi chamado (uma por volta do ciclo ReAct) |
| `input_tokens`, `output_tokens` | O uso informado pelo provedor no fim do stream (`stream_usage`); nulos se ele não informar |
| `tool_calls`, `tool_errors` | Ferramentas executadas e quantas devolveram erro |

A mesma medida sai no log do servidor, uma linha por execução:

```
Execução 3f2c…: completed em 6412 ms (primeira saída em 2810 ms), 2 chamada(s) ao modelo, 7480+212 tokens, 1 ferramenta(s), 0 com erro
```

`GET /api/metrics?days=7` resume as execuções do usuário da sessão: quantas, como terminaram, latência (p50 e p95 da duração e da primeira saída), tokens no total e por execução, taxa de erro das ferramentas e, por modelo, chamadas e tokens. O custo estimado em dólares aparece quando os preços do modelo estão no [`settings.toml`](../../src/agent/config/settings.toml) (`usd_per_million_input` e `usd_per_million_output`); sem eles, fica vazio.

As métricas respondem às perguntas de custo, latência e qualidade de uma troca de modelo ou de prompt: o mesmo período antes e depois, comparado pelo resumo.

## Falhas e recuperação

| Dependência | Quando falha | O que o Graham faz |
|---|---|---|
| Provedor do modelo | 408, 409, 429, 5xx ou conexão | Mais duas tentativas, com espera exponencial (`max_retries` do cliente da OpenAI). Esgotadas, a execução termina com `RUN_ERROR`, a resposta fica `failed` e o usuário pode regerar. |
| Yahoo Finance | Timeout ou conexão caída | Mais duas tentativas do próprio yfinance (1 s e 2 s). Um dado que não vem vira ausência (`None`, `unavailable`) sem derrubar o resto do resultado, e um resultado vazio não entra no cache. |
| Feed de notícias por ticker da Yahoo | Responde vazio desde 2026 | A ferramenta busca pelo nome da empresa e avisa que as notícias vêm sem resumo. |
| Google News | 429, 5xx ou erro de transporte | Mais duas tentativas (0,5 s e 1 s); depois, um erro legível ao modelo. |
| Uma ferramenta | Erro previsto (ticker inexistente, venda maior que a posição) ou exceção | O erro volta ao modelo como resultado da ferramenta, que corrige o pedido ou explica; o turno não cai. Conta em `tool_errors`. |
| Embeddings | 429, 5xx ou conexão | Mais duas tentativas. Sem embedding, a memória é encontrada pela busca lexical, e a subida seguinte completa os que faltaram. |
| Modelo de decisão (Jev) | Qualquer falha | Nenhuma memória é substituída. |
| Redis, como cache | Indisponível | Falha aberto: os dados vêm direto da Yahoo. |
| Redis, como stream | Indisponível | O servidor não sobe: sem ele, uma resposta não sobrevive à conexão. |
| Conexão do navegador | Cai ou a página recarrega | A execução continua em segundo plano; a tela retoma pelo `connect` ou pelo `Last-Event-ID`. |
| O próprio servidor | Para no meio de um turno | Na subida seguinte, a resposta em geração vira `interrupted`, e o stream recebe um `RUN_ERROR` com esse código. |
| Postgres | Migration pendente | O servidor se recusa a subir e diz qual falta. |
| Uma confirmação esquecida | Ninguém responde ao cartão | Expira em um dia, junto com o checkpoint do turno. |

Os detalhes de cada mecanismo estão em [A interface e o AG-UI](interface.md) (streams e retomada), [Persistência](persistencia.md) (cache) e [Carteira e dados de mercado](carteira-e-mercado.md) (particularidades da Yahoo).
