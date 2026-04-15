CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    handle text NOT NULL UNIQUE,
    email text UNIQUE,
    display_name text NOT NULL,
    account_type text NOT NULL DEFAULT 'USER',
    status text NOT NULL DEFAULT 'ACTIVE',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (account_type IN ('USER', 'ADMIN', 'SYNTHETIC_TRADER')),
    CHECK (status IN ('ACTIVE', 'SUSPENDED', 'CLOSED'))
);

CREATE TABLE players (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    provider_player_id text NOT NULL,
    display_name text NOT NULL,
    club text,
    position text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_player_id)
);

CREATE TABLE instruments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_type text NOT NULL,
    player_id uuid REFERENCES players(id),
    symbol text NOT NULL UNIQUE,
    display_name text NOT NULL,
    current_price numeric(18, 4) NOT NULL,
    shares_outstanding numeric(18, 6) NOT NULL,
    price_impact_unit numeric(18, 6) NOT NULL,
    trading_status text NOT NULL DEFAULT 'ACTIVE',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (instrument_type IN ('PLAYER_SHARE')),
    CHECK (
        (instrument_type = 'PLAYER_SHARE' AND player_id IS NOT NULL)
    ),
    CHECK (current_price >= 0),
    CHECK (shares_outstanding >= 0),
    CHECK (price_impact_unit >= 0),
    CHECK (trading_status IN ('ACTIVE', 'FROZEN', 'DELISTED'))
);

CREATE UNIQUE INDEX instruments_player_share_player_id_key
    ON instruments(player_id)
    WHERE instrument_type = 'PLAYER_SHARE';

CREATE INDEX instruments_trading_status_idx
    ON instruments(trading_status);

CREATE TABLE portfolios (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL REFERENCES accounts(id),
    cash_balance numeric(20, 4) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (account_id)
);

CREATE TABLE positions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id uuid NOT NULL REFERENCES portfolios(id),
    instrument_id uuid NOT NULL REFERENCES instruments(id),
    quantity numeric(18, 6) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (portfolio_id, instrument_id),
    CHECK (quantity >= 0)
);

CREATE INDEX positions_instrument_id_idx
    ON positions(instrument_id);

CREATE TABLE orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id text NOT NULL UNIQUE,
    account_id uuid NOT NULL REFERENCES accounts(id),
    portfolio_id uuid NOT NULL REFERENCES portfolios(id),
    instrument_id uuid NOT NULL REFERENCES instruments(id),
    side text NOT NULL,
    shares numeric(18, 6) NOT NULL,
    status text NOT NULL DEFAULT 'PENDING',
    rejection_reason text,
    submitted_at timestamptz NOT NULL DEFAULT now(),
    filled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (side IN ('BUY', 'SELL')),
    CHECK (shares > 0),
    CHECK (status IN ('PENDING', 'FILLED', 'REJECTED', 'FAILED')),
    CHECK (
        status <> 'REJECTED'
        OR rejection_reason IS NOT NULL
    )
);

CREATE INDEX orders_account_id_submitted_at_idx
    ON orders(account_id, submitted_at DESC);

CREATE INDEX orders_portfolio_id_submitted_at_idx
    ON orders(portfolio_id, submitted_at DESC);

CREATE INDEX orders_instrument_id_submitted_at_idx
    ON orders(instrument_id, submitted_at DESC);

CREATE INDEX orders_status_idx
    ON orders(status);

CREATE TABLE trades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id uuid NOT NULL UNIQUE REFERENCES orders(id),
    account_id uuid NOT NULL REFERENCES accounts(id),
    portfolio_id uuid NOT NULL REFERENCES portfolios(id),
    instrument_id uuid NOT NULL REFERENCES instruments(id),
    side text NOT NULL,
    shares numeric(18, 6) NOT NULL,
    execution_price numeric(18, 4) NOT NULL,
    gross_amount numeric(20, 4) NOT NULL,
    executed_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (side IN ('BUY', 'SELL')),
    CHECK (shares > 0),
    CHECK (execution_price >= 0),
    CHECK (gross_amount >= 0)
);

CREATE INDEX trades_account_id_executed_at_idx
    ON trades(account_id, executed_at DESC);

CREATE INDEX trades_portfolio_id_executed_at_idx
    ON trades(portfolio_id, executed_at DESC);

CREATE INDEX trades_instrument_id_executed_at_idx
    ON trades(instrument_id, executed_at DESC);

CREATE TABLE cash_ledger_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL REFERENCES accounts(id),
    portfolio_id uuid NOT NULL REFERENCES portfolios(id),
    trade_id uuid REFERENCES trades(id),
    reason text NOT NULL,
    amount_delta numeric(20, 4) NOT NULL,
    balance_after numeric(20, 4) NOT NULL,
    source_request_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        reason IN (
            'TRADE_BUY_DEBIT',
            'TRADE_SELL_CREDIT',
            'WEEKLY_TOPUP',
            'MONTHLY_TOPUP',
            'ADMIN_ADJUSTMENT',
            'REVERSAL'
        )
    ),
    CHECK (amount_delta <> 0),
    CHECK (
        (reason = 'TRADE_BUY_DEBIT' AND amount_delta < 0)
        OR (reason <> 'TRADE_BUY_DEBIT')
    ),
    CHECK (
        (reason IN ('TRADE_SELL_CREDIT', 'WEEKLY_TOPUP', 'MONTHLY_TOPUP') AND amount_delta > 0)
        OR (reason NOT IN ('TRADE_SELL_CREDIT', 'WEEKLY_TOPUP', 'MONTHLY_TOPUP'))
    )
);

CREATE INDEX cash_ledger_entries_account_id_created_at_idx
    ON cash_ledger_entries(account_id, created_at DESC);

CREATE INDEX cash_ledger_entries_portfolio_id_created_at_idx
    ON cash_ledger_entries(portfolio_id, created_at DESC);

CREATE UNIQUE INDEX cash_ledger_entries_source_request_id_key
    ON cash_ledger_entries(source_request_id)
    WHERE source_request_id IS NOT NULL;

CREATE TABLE price_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id uuid NOT NULL REFERENCES instruments(id),
    old_price numeric(18, 4) NOT NULL,
    new_price numeric(18, 4) NOT NULL,
    reason text NOT NULL,
    trade_id uuid REFERENCES trades(id),
    captured_at timestamptz NOT NULL DEFAULT now(),
    CHECK (old_price >= 0),
    CHECK (new_price >= 0),
    CHECK (reason IN ('SEED', 'TRADE_BUY', 'TRADE_SELL', 'ADMIN_ADJUSTMENT'))
);

CREATE INDEX price_snapshots_instrument_id_captured_at_idx
    ON price_snapshots(instrument_id, captured_at DESC);

CREATE TABLE idempotency_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    command_scope text NOT NULL,
    request_key text NOT NULL,
    request_hash text,
    status text NOT NULL DEFAULT 'STARTED',
    response_status_code integer,
    response_body jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (command_scope, request_key),
    CHECK (
        command_scope IN (
            'ORDER_EXECUTION',
            'TOPUP',
            'ADMIN_ADJUSTMENT',
            'FREEZE',
            'UNFREEZE'
        )
    ),
    CHECK (status IN ('STARTED', 'COMPLETED', 'FAILED')),
    CHECK (response_status_code IS NULL OR response_status_code BETWEEN 100 AND 599)
);

CREATE INDEX idempotency_keys_created_at_idx
    ON idempotency_keys(created_at DESC);

INSERT INTO accounts (
    id,
    handle,
    email,
    display_name,
    account_type,
    status
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    'test-user',
    'test-user@stockball.local',
    'Test User',
    'USER',
    'ACTIVE'
);

INSERT INTO portfolios (
    id,
    account_id,
    cash_balance
) VALUES (
    '00000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001',
    100000.0000
);

INSERT INTO players (
    id,
    provider,
    provider_player_id,
    display_name,
    club,
    position
) VALUES (
    '00000000-0000-0000-0000-000000000003',
    'seed',
    'seed-player-1',
    'Seed Player',
    'Seed FC',
    'MID'
);

INSERT INTO instruments (
    id,
    instrument_type,
    player_id,
    symbol,
    display_name,
    current_price,
    shares_outstanding,
    price_impact_unit,
    trading_status
) VALUES (
    '00000000-0000-0000-0000-000000000004',
    'PLAYER_SHARE',
    '00000000-0000-0000-0000-000000000003',
    'SEED-PLAYER',
    'Seed Player Share',
    100.0000,
    1000000.000000,
    0.010000,
    'ACTIVE'
);

INSERT INTO cash_ledger_entries (
    id,
    account_id,
    portfolio_id,
    reason,
    amount_delta,
    balance_after,
    source_request_id
) VALUES (
    '00000000-0000-0000-0000-000000000005',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000002',
    'ADMIN_ADJUSTMENT',
    100000.0000,
    100000.0000,
    'seed:test-user-opening-cash'
);

INSERT INTO price_snapshots (
    id,
    instrument_id,
    old_price,
    new_price,
    reason
) VALUES (
    '00000000-0000-0000-0000-000000000006',
    '00000000-0000-0000-0000-000000000004',
    100.0000,
    100.0000,
    'SEED'
);
