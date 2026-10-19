# Segurança

O Graham roda só na máquina do usuário ([ADR 0001](../adr/0001-graham-roda-so-localmente.md)), então a superfície é menor que a de um serviço público. Ainda assim, há três caminhos para o agente fazer o que não devia ou expor um dado: texto de terceiros no contexto do modelo, agentes externos pelo MCP e o próprio navegador.

**O que se protege:** a carteira, a watchlist e a alocação, que o agente grava em nome do usuário; a memória e o perfil; as conversas; as chaves de acesso e as sessões.

## Ameaças e defesas

| Ameaça | Defesa | Onde |
|---|---|---|
| **Prompt injection indireto:** um título de notícia manda o agente gravar algo, revelar a carteira ou mudar a memória | Nenhuma gravação acontece sem o usuário: o grafo para no cartão de confirmação, e o modelo não tem como pular essa etapa. O texto das notícias chega sem caracteres invisíveis ou de controle e com tamanho limitado. O prompt e as convenções do MCP dizem que texto de ferramenta é dado, não instrução. Um eval com três injeções exige zero ações proibidas em todas as tentativas. | [`state_graph.py`](../../src/agent/runtime/state_graph.py), [`schemas/market.py`](../../src/tools/schemas/market.py), [`test_injection.py`](../../tests/evals/test_injection.py) |
| **Histórico forjado pelo cliente:** resultados de ferramenta, falas do agente ou confirmações falsas enviadas no AG-UI | O servidor é a fonte da verdade do histórico: do cliente só vale a pergunta nova. A resposta a um cartão é conferida contra a pausa gravada e validada pelo schema da ferramenta, e o ativo não se edita no cartão. | [`agui.py`](../../src/server/agui.py), [`agent.py`](../../src/server/agent.py) |
| **Agente externo gravando sem permissão** | A chave nasce só de leitura; gravar exige o escopo de escrita, marcado ao criá-la. As ferramentas que gravam vêm anotadas como destrutivas, para o cliente pedir confirmação. | [`mcp_server/server.py`](../../src/mcp_server/server.py) |
| **Agente externo lendo ou alterando a memória** | A memória não é publicada pelo MCP: é só do Graham. | [`agent/tools/`](../../src/agent/tools/) |
| **Um usuário vendo dados de outro** | Toda consulta filtra pelo usuário da sessão ou do token. Um teste de integração confirma que a chave de uma conta não vê a carteira de outra. | [`storage/`](../../src/storage/), [`test_mcp.py`](../../tests/integration/test_mcp.py) |
| **Chave ou sessão roubada de uma cópia do banco** | Só o SHA-256 de chaves, tokens internos e sessões fica guardado; senhas com bcrypt. O login dá a mesma resposta, no mesmo tempo, para e-mail inexistente e senha errada, e bloqueia o e-mail por 15 minutos depois de dez erros. | [`auth.py`](../../src/server/auth.py), [`tokens.py`](../../src/storage/tokens.py) |
| **HTML injetado pela resposta do modelo ou pela Yahoo** | Todo texto é escapado antes de virar HTML; tabelas e cartões usam `textContent`. | [`js/markdown.js`](../../src/server/static/js/markdown.js) |
| **Acesso pela rede** | As portas ficam presas a `127.0.0.1`, e o MCP aceita só os hosts e as origens locais. | [`compose.yaml`](../../compose.yaml), [`mcp_server/server.py`](../../src/mcp_server/server.py) |
| **Dados indo para a nuvem** | Só o provedor do modelo e, se ligada, a LangSmith recebem o conteúdo das conversas. | [ADR 0001](../adr/0001-graham-roda-so-localmente.md) |

## O que não está coberto

- **O eval de injeção detecta regressão, não prova robustez.** São três cenários, cada um com três tentativas. Rodados sem a regra no prompt, eles também passam com o modelo atual: a limpeza e a regra são defesa em profundidade, e a garantia de verdade é o cartão.
- **O agente não verifica fatos.** Ele atribui cada notícia ao veículo e à data, mas pode resumir uma notícia falsa como se fosse verdadeira.
- **Não há limite de taxa** nas chaves de acesso nem cota de uso do modelo. Num uso local, o custo é do próprio usuário, e as [métricas por execução](operacao.md) mostram quanto foi gasto.
- **As leituras feitas pelas chaves não têm trilha de auditoria:** só a data do último uso de cada chave fica registrada.
- **A injeção direta**, o próprio usuário pedindo algo ao agente, não é uma ameaça aqui: ele é o dono dos dados.
