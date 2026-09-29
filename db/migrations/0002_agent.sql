-- Conversas e memória de longo prazo do agente.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA agent;

CREATE TYPE agent.message_role AS ENUM ('user', 'assistant', 'tool');

CREATE TYPE agent.message_state AS ENUM (
    'streaming',    -- em geração
    'completed',    -- gerada por inteiro
    'interrupted',  -- o cliente desconectou ou o servidor caiu no meio
    'failed'        -- a geração terminou em erro
);

CREATE TYPE agent.memory_category AS ENUM (
    'perfil',       -- tolerância a risco, horizonte de investimento
    'preferencia',  -- formato de resposta, moeda de referência
    'interesse',    -- ativos e setores que o usuário acompanha
    'episodio',     -- acontecimentos que valem ser lembrados
    'conversa'      -- um turno de conversa, indexado para ser revisitado
);


-- Threads -------------------------------------------------------------------

CREATE TABLE agent.threads (
    id                     uuid        PRIMARY KEY DEFAULT uuidv7(),
    user_id                uuid        NOT NULL REFERENCES core.users (id),
    title                  text,
    -- Num fork, aponta para a mensagem de outra thread de onde ele partiu. O
    -- histórico anterior não é copiado: o caminho sobe pelos `parent_id`.
    forked_from_message_id uuid,
    -- Última mensagem do caminho ativo. Num fork recém-criado, é o próprio
    -- ponto de bifurcação.
    head_message_id        uuid,
    created_at             timestamptz NOT NULL DEFAULT now(),
    archived_at            timestamptz
);

CREATE INDEX threads_user_idx
    ON agent.threads (user_id, created_at DESC)
    WHERE archived_at IS NULL;


-- Mensagens -----------------------------------------------------------------

-- As mensagens formam uma árvore: regerar uma resposta ou editar uma pergunta
-- cria uma irmã, e um fork continua a partir de um nó de outra thread.
CREATE TABLE agent.messages (
    id         uuid                PRIMARY KEY DEFAULT uuidv7(),
    -- Thread onde a mensagem foi criada; o `parent_id` pode estar em outra.
    thread_id  uuid                NOT NULL REFERENCES agent.threads (id),
    parent_id  uuid                REFERENCES agent.messages (id),
    -- Posição no caminho, preenchida por trigger. Irmãs têm o mesmo valor.
    seq        integer             NOT NULL,
    role       agent.message_role  NOT NULL,
    state      agent.message_state NOT NULL,
    content    text                NOT NULL DEFAULT '',
    -- Tool calls de uma mensagem do assistente, ou identificação e retorno
    -- bruto de uma mensagem de ferramenta.
    payload    jsonb,
    -- Modelo e parâmetros usados na geração, para reproduzir a resposta.
    model      text,
    params     jsonb,
    created_at timestamptz         NOT NULL DEFAULT now(),

    CONSTRAINT messages_user_completed CHECK (role <> 'user' OR state = 'completed')
);

CREATE INDEX messages_parent_idx ON agent.messages (parent_id);
CREATE INDEX messages_thread_idx ON agent.messages (thread_id, seq);
-- Na subida do servidor, o que ficou em `streaming` é marcado como `interrupted`.
CREATE INDEX messages_streaming_idx ON agent.messages (id) WHERE state = 'streaming';

ALTER TABLE agent.threads
    ADD CONSTRAINT threads_forked_from_message_fk
        FOREIGN KEY (forked_from_message_id) REFERENCES agent.messages (id),
    ADD CONSTRAINT threads_head_message_fk
        FOREIGN KEY (head_message_id) REFERENCES agent.messages (id);

CREATE FUNCTION agent.set_message_seq() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.parent_id IS NULL THEN
        NEW.seq := 1;
    ELSE
        SELECT parent.seq + 1 INTO NEW.seq
        FROM agent.messages AS parent
        WHERE parent.id = NEW.parent_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'A mensagem pai % não existe', NEW.parent_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER messages_set_seq
    BEFORE INSERT ON agent.messages
    FOR EACH ROW EXECUTE FUNCTION agent.set_message_seq();

-- Conteúdo e estado mudam enquanto a resposta é gerada; a posição na árvore,
-- nunca. Mover uma mensagem quebraria o caminho de todo fork que passa por ela.
CREATE FUNCTION agent.freeze_message_position() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.thread_id, NEW.parent_id, NEW.seq, NEW.role, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.thread_id, OLD.parent_id, OLD.seq, OLD.role, OLD.created_at)
    THEN
        RAISE EXCEPTION 'A posição da mensagem % na árvore não pode ser alterada', OLD.id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER messages_freeze_position
    BEFORE UPDATE ON agent.messages
    FOR EACH ROW EXECUTE FUNCTION agent.freeze_message_position();

-- O caminho da primeira mensagem até a informada. Num fork, a subida
-- atravessa a thread de origem até o início.
CREATE FUNCTION agent.message_path(p_message_id uuid)
RETURNS SETOF agent.messages
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE path AS (
        SELECT message.*
        FROM agent.messages AS message
        WHERE message.id = p_message_id

        UNION ALL

        SELECT parent.*
        FROM path
        JOIN agent.messages AS parent ON parent.id = path.parent_id
    )
    SELECT * FROM path ORDER BY seq
$$;

-- O caminho ativo de uma thread: da primeira mensagem até a `head`.
CREATE FUNCTION agent.thread_path(p_thread_id uuid)
RETURNS SETOF agent.messages
LANGUAGE sql STABLE AS $$
    SELECT path.*
    FROM agent.threads AS thread,
         agent.message_path(thread.head_message_id) AS path
    WHERE thread.id = p_thread_id
$$;


-- Memórias ------------------------------------------------------------------

CREATE TABLE agent.memories (
    id                      uuid                  PRIMARY KEY DEFAULT uuidv7(),
    user_id                 uuid                  NOT NULL REFERENCES core.users (id),
    category                agent.memory_category NOT NULL,
    content                 text                  NOT NULL,
    -- pplx-embed-v1 devolve vetores INT8, que o `halfvec` guarda sem perda na
    -- metade do espaço do `vector`. Fica nulo até o embedding ser calculado.
    embedding               halfvec(1024),
    embedding_model         text,
    -- Separar o sufixo da bolsa ('BBAS3.SA' vira 'BBAS3 SA') faz o ticker ser
    -- encontrado com ou sem ele; o parser juntaria os dois num token só.
    tsv                     tsvector GENERATED ALWAYS AS (
        to_tsvector('portuguese', regexp_replace(content, '\.(?=[[:alpha:]])', ' ', 'g'))
    ) STORED,
    -- O fato mudou: aponta para a versão que o substituiu.
    superseded_by_id        uuid                  REFERENCES agent.memories (id),
    -- A memória estava errada ou o usuário pediu para esquecê-la. Nunca é
    -- apagada de verdade: é o sinal de erro para melhorar a geração de memórias.
    is_forgotten            boolean               NOT NULL DEFAULT false,
    forgotten_at            timestamptz,
    forgotten_by_message_id uuid                  REFERENCES agent.messages (id),
    created_at              timestamptz           NOT NULL DEFAULT now(),

    CONSTRAINT memories_embedding_model
        CHECK ((embedding IS NULL) = (embedding_model IS NULL)),
    CONSTRAINT memories_forgotten_at
        CHECK (is_forgotten = (forgotten_at IS NOT NULL)),
    CONSTRAINT memories_forgotten_by
        CHECK (is_forgotten OR forgotten_by_message_id IS NULL)
);

-- Os índices de busca só cobrem o que ainda vale: esquecidas e substituídas
-- ficam na tabela, mas fora do caminho de toda consulta.
CREATE INDEX memories_embedding_idx
    ON agent.memories USING hnsw (embedding halfvec_cosine_ops)
    WHERE NOT is_forgotten AND superseded_by_id IS NULL;

CREATE INDEX memories_tsv_idx
    ON agent.memories USING gin (tsv)
    WHERE NOT is_forgotten AND superseded_by_id IS NULL;

CREATE INDEX memories_user_category_idx
    ON agent.memories (user_id, category)
    WHERE NOT is_forgotten AND superseded_by_id IS NULL;

-- De quais mensagens cada memória saiu. Num fato guardado pelo agente, é a
-- mensagem que chamou a ferramenta; num turno de `conversa`, a pergunta e a
-- resposta final.
CREATE TABLE agent.memory_sources (
    memory_id  uuid NOT NULL REFERENCES agent.memories (id),
    message_id uuid NOT NULL REFERENCES agent.messages (id),
    PRIMARY KEY (memory_id, message_id)
);

CREATE INDEX memory_sources_message_idx ON agent.memory_sources (message_id);

-- Busca híbrida: os vizinhos mais próximos pelo embedding e os melhores
-- resultados lexicais, combinados por Reciprocal Rank Fusion. O lexical acerta
-- tickers e nomes exatos; o semântico, paráfrases. Sem `p_embedding`, a busca
-- fica só com o lexical.
CREATE FUNCTION agent.search_memories(
    p_user_id   uuid,
    p_query     text,
    p_embedding halfvec,
    p_limit     integer DEFAULT 10
)
RETURNS TABLE (
    id         uuid,
    category   agent.memory_category,
    content    text,
    created_at timestamptz,
    score      double precision
)
LANGUAGE sql STABLE AS $$
    WITH semantic AS (
        SELECT nearest.id, row_number() OVER (ORDER BY nearest.distance) AS rank
        FROM (
            SELECT memory.id, memory.embedding <=> p_embedding AS distance
            FROM agent.memories AS memory
            WHERE memory.user_id = p_user_id
              AND NOT memory.is_forgotten
              AND memory.superseded_by_id IS NULL
              AND memory.embedding IS NOT NULL
              AND p_embedding IS NOT NULL
            ORDER BY distance
            LIMIT 40
        ) AS nearest
    ),
    lexical AS (
        SELECT matches.id, row_number() OVER (ORDER BY matches.relevance DESC) AS rank
        FROM (
            SELECT memory.id, ts_rank_cd(memory.tsv, terms.query) AS relevance
            FROM agent.memories AS memory,
                 -- `plainto_tsquery` exige todos os termos; trocar o E pelo OU
                 -- basta um em comum, e o `ts_rank_cd` premia quem tem mais.
                 LATERAL (
                     SELECT replace(
                         plainto_tsquery(
                             'portuguese',
                             regexp_replace(p_query, '\.(?=[[:alpha:]])', ' ', 'g')
                         )::text,
                         '&', '|'
                     )::tsquery AS query
                 ) AS terms
            WHERE memory.user_id = p_user_id
              AND NOT memory.is_forgotten
              AND memory.superseded_by_id IS NULL
              AND memory.tsv @@ terms.query
            ORDER BY relevance DESC
            LIMIT 40
        ) AS matches
    ),
    fused AS (
        -- 60 é a constante usual do RRF: suaviza a vantagem dos primeiros lugares.
        SELECT coalesce(semantic.id, lexical.id) AS id,
               coalesce(1.0 / (60 + semantic.rank), 0)
             + coalesce(1.0 / (60 + lexical.rank), 0) AS score
        FROM semantic
        FULL JOIN lexical ON lexical.id = semantic.id
    )
    SELECT memory.id, memory.category, memory.content, memory.created_at,
           fused.score::double precision
    FROM fused
    JOIN agent.memories AS memory ON memory.id = fused.id
    ORDER BY fused.score DESC
    LIMIT p_limit
$$;
