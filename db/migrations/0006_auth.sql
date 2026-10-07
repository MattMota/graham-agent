-- Autenticação com e-mail e senha. Quem aponta para core.users (conversas,
-- memórias, carteira, watchlist) não muda: o usuário ganha credenciais.

ALTER TABLE core.users
    ADD COLUMN email         text,
    -- bcrypt ($2a$/$2b$): o Postgres gera aqui embaixo, o servidor confere.
    ADD COLUMN password_hash text;

-- O uso anônimo até aqui foi todo de uma mesma pessoa: os usuários anônimos se
-- fundem no mais antigo, que vira a conta user@email.com. Num banco sem
-- usuários nada é criado, para nenhum ambiente nascer com uma senha conhecida.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
    owner_id uuid;
BEGIN
    SELECT id INTO owner_id FROM core.users ORDER BY created_at, id LIMIT 1;
    IF owner_id IS NULL THEN
        RETURN;
    END IF;

    -- Alvos repetidos entre usuários ficariam duplicados na mesma conta:
    -- fica o do dono e, entre os outros, o mais antigo.
    DELETE FROM core.watchlist duplicate
     USING core.watchlist kept
     WHERE duplicate.user_id <> owner_id
       AND kept.id <> duplicate.id
       AND (kept.ticker, kept.operation, kept.target_price)
         = (duplicate.ticker, duplicate.operation, duplicate.target_price)
       AND (kept.user_id = owner_id OR kept.id < duplicate.id);

    UPDATE agent.threads         SET user_id = owner_id WHERE user_id <> owner_id;
    UPDATE agent.memories        SET user_id = owner_id WHERE user_id <> owner_id;
    UPDATE core.portfolio_trades SET user_id = owner_id WHERE user_id <> owner_id;
    UPDATE core.watchlist        SET user_id = owner_id WHERE user_id <> owner_id;
    DELETE FROM core.users WHERE id <> owner_id;

    UPDATE core.users
       SET email = 'user@email.com',
           password_hash = crypt('graham', gen_salt('bf', 12))
     WHERE id = owner_id;
END
$$;

DROP EXTENSION pgcrypto;

-- O e-mail chega minúsculo do servidor; a restrição garante que a unicidade
-- não dependa de caixa.
ALTER TABLE core.users
    ALTER COLUMN email SET NOT NULL,
    ALTER COLUMN password_hash SET NOT NULL,
    ADD CONSTRAINT users_email_key UNIQUE (email),
    ADD CONSTRAINT users_email_lowercase CHECK (email = lower(email));


-- Sessões ------------------------------------------------------------------

-- O cookie leva um token aleatório; aqui fica só o SHA-256 dele, para que uma
-- cópia do banco não sirva para entrar. Sair apaga a linha.
CREATE TABLE core.sessions (
    token_hash bytea       PRIMARY KEY,
    user_id    uuid        NOT NULL REFERENCES core.users (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX sessions_user_idx ON core.sessions (user_id);
CREATE INDEX sessions_expires_idx ON core.sessions (expires_at);
