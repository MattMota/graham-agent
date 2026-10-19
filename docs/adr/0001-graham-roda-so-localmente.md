# O Graham roda só na máquina do usuário

O Graham não é publicado na internet. Para fora dele, existe só o servidor MCP, autenticado por chaves de acesso, para agentes da mesma máquina (Claude Code, Codex, Cursor). Por isso ficaram de fora o OAuth 2.1 no MCP, o protocolo A2A, os conectores do claude.ai e do ChatGPT e qualquer deploy. Todos eles só servem com o servidor alcançável pela internet, e cada um traria um servidor de autorização, registro de clientes e superfície de ataque para manter.

## Considered Options

- **OAuth 2.1 no MCP**: chegou a ser implementado e testado, com login, consentimento, PKCE e registro de clientes, e foi desfeito. Os conectores que o exigem rodam na nuvem do fornecedor e nunca alcançariam um servidor local.
- **A2A**: deixaria outro agente usar o Graham inteiro como par, não só as ferramentas. Ficou de fora pelo mesmo motivo. Também ficaram sem resposta a autenticação do agente cliente, o estado `input-required` para as confirmações e o uso da memória por terceiros.
- **AG-UI aberto a terceiros**: o protocolo ficou só entre a interface do Graham e o agente.

## Consequences

- **A exceção é a LangSmith, e é opcional.** Com `LANGSMITH_TRACING=true`, os traces dos turnos vão para a nuvem dela, com perguntas, carteira e perfil. Ela foi escolhida em vez do Langfuse instalado na máquina para não manter mais um serviço; o plano gratuito, sem cartão, recusa os traces depois do limite em vez de cobrar. Desligada, nada sai da máquina além das consultas à Yahoo, ao Google News e ao provedor do modelo.
- **Uma feature que dependa de acesso pela internet** (túnel, webhook, link de compartilhamento) precisa rever esta decisão primeiro.
