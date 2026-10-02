-- Carteira e watchlist do usuário, e a pausa do agente à espera de confirmação.

CREATE TYPE core.trade_side AS ENUM ('compra', 'venda');

CREATE TYPE core.watch_operation AS ENUM ('compra', 'venda', 'short');


-- Carteira ------------------------------------------------------------------

-- Um livro de operações: cada compra e cada venda é uma linha que nunca muda.
-- A posição e o preço médio de cada ativo são calculados a partir dele, na
-- ordem das datas, porque uma venda reduz a quantidade sem mudar o preço médio.
CREATE TABLE core.portfolio_trades (
    id         uuid            PRIMARY KEY DEFAULT uuidv7(),
    user_id    uuid            NOT NULL REFERENCES core.users (id),
    -- Símbolo da Yahoo Finance, como 'BBAS3.SA'.
    ticker     text            NOT NULL,
    side       core.trade_side NOT NULL,
    -- Decimal: criptomoedas e ações fracionárias no exterior não são inteiras.
    quantity   numeric(24, 8)  NOT NULL CHECK (quantity > 0),
    -- Preço por unidade praticado na operação; o total é calculado.
    unit_price numeric(24, 8)  NOT NULL CHECK (unit_price > 0),
    -- Moeda em que o ativo é cotado. Totais só se somam dentro da mesma moeda.
    currency   text            NOT NULL,
    traded_on  date            NOT NULL,
    created_at timestamptz     NOT NULL DEFAULT now()
);

CREATE INDEX portfolio_trades_user_idx
    ON core.portfolio_trades (user_id, ticker, traded_on, id);


-- Watchlist -----------------------------------------------------------------

-- Ativos que o usuário quer acompanhar, cada um com a operação que pretende
-- fazer ao atingir o preço alvo. O mesmo ativo pode aparecer mais de uma vez:
-- comprar a 20 e vender a 30, ou comprar em etapas a 20 e a 18.
CREATE TABLE core.watchlist (
    id           uuid                 PRIMARY KEY DEFAULT uuidv7(),
    user_id      uuid                 NOT NULL REFERENCES core.users (id),
    ticker       text                 NOT NULL,
    operation    core.watch_operation NOT NULL,
    target_price numeric(24, 8)       NOT NULL CHECK (target_price > 0),
    -- Opcional: transforma o acompanhamento num plano ("comprar 100 a 20").
    quantity     numeric(24, 8)       CHECK (quantity > 0),
    currency     text                 NOT NULL,
    created_at   timestamptz          NOT NULL DEFAULT now(),

    CONSTRAINT watchlist_unique_target UNIQUE (user_id, ticker, operation, target_price)
);


-- Confirmação ---------------------------------------------------------------

-- Um turno pausado à espera de o usuário confirmar operações na carteira ou
-- na watchlist. A mensagem que marca a pausa guarda os pedidos e, depois, as
-- decisões.
ALTER TYPE agent.message_state ADD VALUE 'awaiting_approval' AFTER 'streaming';
