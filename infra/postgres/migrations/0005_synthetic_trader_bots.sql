CREATE TABLE synthetic_trader_bot_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key text NOT NULL UNIQUE,
    display_name text NOT NULL,
    strategy_engine text NOT NULL,
    version integer NOT NULL DEFAULT 1,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        strategy_engine IN (
            'NOISE',
            'MARKET_MOMENTUM',
            'STATS_VALUE',
            'SOCIAL_SENTIMENT',
            'PORTFOLIO_REBALANCER'
        )
    ),
    CHECK (version > 0),
    CHECK (jsonb_typeof(config) = 'object')
);

CREATE UNIQUE INDEX synthetic_trader_bot_configs_key_version_key
    ON synthetic_trader_bot_configs(config_key, version);

CREATE INDEX synthetic_trader_bot_configs_strategy_engine_idx
    ON synthetic_trader_bot_configs(strategy_engine);

CREATE TABLE synthetic_trader_bots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id uuid NOT NULL UNIQUE REFERENCES accounts(id),
    config_id uuid NOT NULL REFERENCES synthetic_trader_bot_configs(id),
    bot_key text NOT NULL UNIQUE,
    display_name text NOT NULL,
    status text NOT NULL DEFAULT 'ACTIVE',
    config_overrides jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_ticked_at timestamptz,
    next_tick_after timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('ACTIVE', 'PAUSED', 'RETIRED')),
    CHECK (jsonb_typeof(config_overrides) = 'object')
);

CREATE INDEX synthetic_trader_bots_config_id_idx
    ON synthetic_trader_bots(config_id);

CREATE INDEX synthetic_trader_bots_status_next_tick_idx
    ON synthetic_trader_bots(status, next_tick_after);
