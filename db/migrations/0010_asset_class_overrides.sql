-- A classe que o usuário escolheu para um ativo, no lugar da automática (que
-- sai do tipo e do nome na Yahoo). Classificar o IVVB11 como exterior é uma
-- visão de carteira, não um fato: por isso a escolha é por usuário.

CREATE TABLE core.asset_class_overrides (
    user_id     uuid        NOT NULL REFERENCES core.users (id),
    -- Símbolo da Yahoo Finance, como 'IVVB11.SA'.
    ticker      text        NOT NULL,
    -- Uma das classes da alocação-alvo, ou 'fora' para deixar o ativo fora da conta.
    asset_class text        NOT NULL
        CHECK (asset_class IN ('acoes_br', 'fundos', 'etfs', 'exterior', 'cripto', 'fora')),
    updated_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, ticker)
);
