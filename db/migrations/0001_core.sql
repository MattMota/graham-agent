-- Schema compartilhado entre o agente e os demais domínios (carteira, watchlist).

CREATE SCHEMA core;

-- Por enquanto o usuário é anônimo, identificado por um cookie. A autenticação
-- entra depois (0006_auth.sql), sem mudar quem aponta para cá.
CREATE TABLE core.users (
    id         uuid        PRIMARY KEY DEFAULT uuidv7(),
    created_at timestamptz NOT NULL DEFAULT now()
);
