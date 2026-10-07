-- Renomear, apagar e buscar conversas.

-- Apagar é esconder: uma bifurcação sobe pelos `parent_id` até as mensagens da
-- conversa de origem, que por isso continuam gravadas. A coluna `archived_at`,
-- reservada desde o início e nunca usada, passa a ter esse papel; o índice da
-- listagem já filtra por ela.
ALTER TABLE agent.threads RENAME COLUMN archived_at TO deleted_at;

-- A busca ignora acentos: "acao" encontra "ação".
CREATE EXTENSION IF NOT EXISTS unaccent;
