-- Tokens de acesso ao servidor MCP.
--
-- Dois tipos, verificados do mesmo jeito: a chave que o usuário cria para um
-- agente próprio (com nome e sem prazo, até ser revogada) e o token interno
-- que o Graham emite a cada turno para chamar o MCP em nome do usuário (curto,
-- apagado ao fim do turno). Como nas sessões, guarda-se só o SHA-256.

CREATE TABLE core.access_tokens (
    id           uuid        PRIMARY KEY DEFAULT uuidv7(),
    user_id      uuid        NOT NULL REFERENCES core.users (id) ON DELETE CASCADE,
    token_hash   bytea       NOT NULL UNIQUE,
    kind         text        NOT NULL CHECK (kind IN ('chave', 'interno')),
    name         text,
    -- graham:leitura sempre; graham:escrita quando a chave pode gravar.
    scopes       text[]      NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    expires_at   timestamptz,
    revoked_at   timestamptz,

    CONSTRAINT access_tokens_named_key CHECK (kind <> 'chave' OR name IS NOT NULL),
    CONSTRAINT access_tokens_internal_expires CHECK (kind <> 'interno' OR expires_at IS NOT NULL)
);

CREATE INDEX access_tokens_user_idx ON core.access_tokens (user_id, created_at DESC) WHERE kind = 'chave';
CREATE INDEX access_tokens_expires_idx ON core.access_tokens (expires_at) WHERE expires_at IS NOT NULL;
