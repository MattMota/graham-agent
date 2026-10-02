-- A moeda em que o usuário pagou deixa de ser, obrigatoriamente, a moeda em que
-- o ativo é cotado. Bitcoin comprado em reais é cotado pela Yahoo em dólar
-- (BTC-USD): o preço e o custo ficam em reais, e só o valor atual é convertido,
-- com o câmbio do momento da consulta. Nenhum câmbio histórico é necessário.

ALTER TABLE core.portfolio_trades RENAME COLUMN currency TO price_currency;

-- Até aqui as duas moedas eram a mesma.
ALTER TABLE core.portfolio_trades ADD COLUMN quote_currency text;
UPDATE core.portfolio_trades SET quote_currency = price_currency;
ALTER TABLE core.portfolio_trades ALTER COLUMN quote_currency SET NOT NULL;

COMMENT ON COLUMN core.portfolio_trades.price_currency IS
    'Moeda do preço unitário, a que o usuário pagou. Uma só por ativo e usuário, para o preço médio não misturar moedas.';
COMMENT ON COLUMN core.portfolio_trades.quote_currency IS
    'Moeda em que a Yahoo Finance cota o ativo, usada para converter o valor atual.';
