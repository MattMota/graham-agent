-- Alocação-alvo do usuário: o peso que ele quer para cada classe de ativo e a
-- banda de tolerância do enquadramento (docs/adr/0004). Uma por usuário; uma
-- definição nova substitui a anterior.

CREATE TABLE core.allocation_targets (
    user_id    uuid         PRIMARY KEY REFERENCES core.users (id),
    -- Pesos em pontos percentuais, somando 100.
    acoes_br   numeric(5, 2) NOT NULL CHECK (acoes_br BETWEEN 0 AND 100),
    fundos     numeric(5, 2) NOT NULL CHECK (fundos BETWEEN 0 AND 100),
    etfs       numeric(5, 2) NOT NULL CHECK (etfs BETWEEN 0 AND 100),
    exterior   numeric(5, 2) NOT NULL CHECK (exterior BETWEEN 0 AND 100),
    cripto     numeric(5, 2) NOT NULL CHECK (cripto BETWEEN 0 AND 100),
    -- Quantos pontos percentuais uma classe pode se afastar do alvo.
    tolerance  numeric(5, 2) NOT NULL DEFAULT 5 CHECK (tolerance BETWEEN 0 AND 50),
    updated_at timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT allocation_targets_sum CHECK (acoes_br + fundos + etfs + exterior + cripto = 100)
);

COMMENT ON TABLE core.allocation_targets IS
    'Alocação-alvo por classe de ativo, definida e confirmada pelo usuário.';
