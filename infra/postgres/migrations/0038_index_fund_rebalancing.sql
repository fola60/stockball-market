-- Index funds that follow a rule. The worker re-evaluates each fund's rule and the trading
-- engine rebalances the basket to match, trading the custody account from the old basket to the
-- new one without changing what a unit is worth. Players who leave the league are bought out at
-- their last price, which turns any fund holding into cash until the next rebalance spends it.

-- Cash held per unit, from delisting buyouts and rebalancing remainders. A unit is worth its
-- basket at current prices plus this cash, which the custody portfolio holds.
ALTER TABLE index_funds
    ADD COLUMN cash_per_unit numeric(28, 12) NOT NULL DEFAULT 0,
    ADD CONSTRAINT index_funds_cash_per_unit_check CHECK (cash_per_unit >= 0);

-- Every basket change: rebalances to a new rule result and removals by delisting.
CREATE TABLE index_fund_rebalances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id text NOT NULL UNIQUE,
    index_instrument_id uuid NOT NULL REFERENCES index_funds(instrument_id),
    kind text NOT NULL CHECK (kind IN ('REBALANCE', 'DELISTING')),
    reason text NOT NULL,
    units_outstanding numeric(18, 6) NOT NULL,
    unit_price_before numeric(28, 12) NOT NULL,
    unit_price_after numeric(28, 12) NOT NULL,
    cash_per_unit_after numeric(28, 12) NOT NULL,
    -- [{"instrument_id": ..., "shares_per_unit": ...}] before and after.
    old_basket jsonb NOT NULL,
    new_basket jsonb NOT NULL,
    added_instrument_ids uuid[] NOT NULL DEFAULT '{}',
    removed_instrument_ids uuid[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX index_fund_rebalances_fund_created_at_idx
    ON index_fund_rebalances (index_instrument_id, created_at DESC);

-- A rebalance's custody trades point at the rebalance, as unit-trade legs point at their fund
-- trade.
ALTER TABLE trades
    ADD COLUMN index_rebalance_id uuid REFERENCES index_fund_rebalances(id);

CREATE INDEX trades_index_rebalance_id_idx
    ON trades (index_rebalance_id)
    WHERE index_rebalance_id IS NOT NULL;

-- INDEX_FUND_CASH_IN and _OUT move a unit's cash between a trader and custody when units are
-- bought or sold. DELISTING_BUYOUT pays a holder for a share that left the market.
ALTER TABLE cash_ledger_entries
    DROP CONSTRAINT cash_ledger_entries_reason_check,
    ADD CONSTRAINT cash_ledger_entries_reason_check CHECK (
        reason IN (
            'TRADE_BUY_DEBIT',
            'TRADE_SELL_CREDIT',
            'WEEKLY_TOPUP',
            'MONTHLY_TOPUP',
            'OPENING_BALANCE',
            'ADMIN_ADJUSTMENT',
            'REVERSAL',
            'INDEX_FUND_CASH_IN',
            'INDEX_FUND_CASH_OUT',
            'DELISTING_BUYOUT'
        )
    ),
    DROP CONSTRAINT cash_ledger_entries_check,
    ADD CONSTRAINT cash_ledger_entries_check CHECK (
        (
            reason IN (
                'TRADE_SELL_CREDIT',
                'WEEKLY_TOPUP',
                'MONTHLY_TOPUP',
                'OPENING_BALANCE',
                'INDEX_FUND_CASH_IN',
                'DELISTING_BUYOUT'
            )
            AND amount_delta > 0
        )
        OR reason NOT IN (
            'TRADE_SELL_CREDIT',
            'WEEKLY_TOPUP',
            'MONTHLY_TOPUP',
            'OPENING_BALANCE',
            'INDEX_FUND_CASH_IN',
            'DELISTING_BUYOUT'
        )
    ),
    ADD CONSTRAINT cash_ledger_entries_cash_out_check CHECK (
        reason <> 'INDEX_FUND_CASH_OUT' OR amount_delta < 0
    );

-- When a delisted player returns to the league they get a new share, so only a live share is
-- unique per player.
DROP INDEX instruments_player_share_player_id_key;
CREATE UNIQUE INDEX instruments_player_share_player_id_key
    ON instruments (player_id)
    WHERE instrument_type = 'PLAYER_SHARE' AND trading_status <> 'DELISTED';
