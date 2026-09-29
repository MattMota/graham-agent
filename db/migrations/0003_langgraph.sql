-- Schema dos checkpoints do LangGraph. As tabelas não são nossas: o
-- `AsyncPostgresSaver.setup()` as cria e migra na subida do servidor, dentro
-- deste schema, porque a conexão dele usa `search_path = langgraph`.
--
-- Os checkpoints são estado de execução, não histórico: cada turno roda numa
-- thread própria do LangGraph e é apagado um dia depois. O histórico da
-- conversa vive em `agent.messages`.

CREATE SCHEMA langgraph;
