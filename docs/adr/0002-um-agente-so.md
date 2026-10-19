# Um agente só, num grafo próprio

O Graham é um único agente ReAct, num grafo do LangGraph escrito à mão: os nós `agent`, `approval` e `tools`. Não há subagentes, nem o pacote Deep Agents. As tarefas do Graham são turnos curtos, de uma ou duas rodadas de ferramentas: cotação, carteira, proventos, agenda. Planejamento, sistema de arquivos virtual e delegação a subagentes só somariam tokens e latência. O grafo próprio é o que a confirmação das operações e a tradução para o AG-UI conhecem pelo nome.

## Considered Options

- **Deep Agents (`create_deep_agent`)**: sugerido pelo onboarding da LangSmith, que não precisa dele para rastrear. Ele traz plano de tarefas (`write_todos`), arquivos virtuais e subagentes, para tarefas longas e abertas. Adotá-lo significaria refazer o nó de aprovação, os eventos do AG-UI (`runs.py` reage aos nós pelo nome) e a gravação dos turnos. O que ele oferece de útil aqui, o Graham já tem: as skills são carregadas sob demanda com `ler_skill`, e a confirmação humana é um nó do grafo.
- **Multi-agente** (um agente de pesquisa, outro de carteira, um orquestrador): cada passagem entre agentes custa uma chamada ao modelo e perde contexto, e nenhuma tarefa atual precisa de paralelismo entre especialistas. A separação por assunto já acontece nas skills e nos grupos de ferramentas do MCP.

## Consequences

- **Quando rever:** quando o Graham ganhar tarefas longas e abertas, como "monte um relatório comparando todos os bancos da B3, com fundamentos e notícias". Antes de trazer um framework, vale ver se um subagente como nó do próprio grafo resolve.
