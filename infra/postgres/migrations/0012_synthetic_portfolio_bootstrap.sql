-- Dedicated custody account for player-share supply retained outside bot portfolios.
-- ADMIN is used because reserve accounts are internal and cannot authenticate or run a bot.
INSERT INTO accounts (id, handle, display_name, account_type, status)
VALUES (
    '7f63e2d0-1adc-4af1-8ad0-000000000001',
    'system-player-share-reserve',
    'Player Share Reserve',
    'ADMIN',
    'ACTIVE'
);

INSERT INTO portfolios (id, account_id, cash_balance)
VALUES (
    '7f63e2d0-1adc-4af1-8ad0-000000000002',
    '7f63e2d0-1adc-4af1-8ad0-000000000001',
    0
);

CREATE TABLE synthetic_portfolio_bootstrap_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    seed bigint NOT NULL,
    parameters jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(parameters) = 'object')
);

CREATE TABLE synthetic_portfolio_bootstrap_allocations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id uuid NOT NULL REFERENCES synthetic_portfolio_bootstrap_batches(id),
    instrument_id uuid NOT NULL REFERENCES instruments(id),
    portfolio_id uuid NOT NULL REFERENCES portfolios(id),
    bot_id uuid REFERENCES synthetic_trader_bots(id),
    quantity numeric(18, 0) NOT NULL,
    seed_price numeric(18, 4) NOT NULL,
    is_reserve boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (quantity > 0),
    CHECK (seed_price >= 0),
    CHECK (
        (is_reserve AND bot_id IS NULL AND portfolio_id = '7f63e2d0-1adc-4af1-8ad0-000000000002')
        OR (NOT is_reserve AND bot_id IS NOT NULL)
    ),
    UNIQUE (batch_id, instrument_id, portfolio_id)
);

-- Every processed instrument has exactly one reserve row, making issuance one-off.
CREATE UNIQUE INDEX synthetic_portfolio_bootstrap_instrument_once_idx
    ON synthetic_portfolio_bootstrap_allocations(instrument_id)
    WHERE is_reserve;

CREATE INDEX synthetic_portfolio_bootstrap_allocations_batch_idx
    ON synthetic_portfolio_bootstrap_allocations(batch_id);

CREATE INDEX synthetic_portfolio_bootstrap_allocations_bot_idx
    ON synthetic_portfolio_bootstrap_allocations(bot_id)
    WHERE bot_id IS NOT NULL;
