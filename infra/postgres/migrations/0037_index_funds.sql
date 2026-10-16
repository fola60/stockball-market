-- Index funds: an instrument whose unit is a fixed basket of player shares. Buying a unit buys
-- each player's shares on that player's own price curve, so the fund's price is always the
-- value of its basket and only trades move it. The shares are held by a custody account.

-- Custody for the player shares behind every index fund unit. ADMIN, like the share reserve,
-- because it cannot authenticate or run a bot, and it stays off leaderboards and trade feeds.
INSERT INTO accounts (id, handle, display_name, account_type, status)
VALUES (
    '7f63e2d0-1adc-4af1-8ad0-000000000003',
    'system-index-fund-custody',
    'Index Fund Custody',
    'ADMIN',
    'ACTIVE'
);

INSERT INTO portfolios (id, account_id, cash_balance)
VALUES (
    '7f63e2d0-1adc-4af1-8ad0-000000000004',
    '7f63e2d0-1adc-4af1-8ad0-000000000003',
    0
);

-- An index fund has no player and no price curve of its own. Its units are issued on demand,
-- so it has no fixed supply either.
ALTER TABLE instruments
    DROP CONSTRAINT instruments_instrument_type_check,
    DROP CONSTRAINT instruments_check,
    ALTER COLUMN shares_outstanding DROP NOT NULL,
    ALTER COLUMN reference_price DROP NOT NULL,
    ALTER COLUMN full_supply_price_multiplier DROP NOT NULL,
    ALTER COLUMN curve_depth_shares DROP NOT NULL,
    ADD CONSTRAINT instruments_instrument_type_check
        CHECK (instrument_type IN ('PLAYER_SHARE', 'INDEX_FUND')),
    ADD CONSTRAINT instruments_player_share_terms_check CHECK (
        (
            instrument_type = 'PLAYER_SHARE'
            AND player_id IS NOT NULL
            AND shares_outstanding IS NOT NULL
            AND reference_price IS NOT NULL
            AND full_supply_price_multiplier IS NOT NULL
            AND curve_depth_shares IS NOT NULL
        )
        OR (
            instrument_type = 'INDEX_FUND'
            AND player_id IS NULL
            AND shares_outstanding IS NULL
            AND reference_price IS NULL
            AND full_supply_price_multiplier IS NULL
            AND curve_depth_shares IS NULL
            AND net_shares_purchased = 0
        )
    );

-- A fund's price is the value of its basket, set by the trading engine whenever a constituent
-- trades, so it is exempt from the curve rule that ties a price change to net demand.
CREATE OR REPLACE FUNCTION enforce_instrument_price_curve_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.instrument_type = 'INDEX_FUND' THEN
        RETURN NEW;
    END IF;

    IF NEW.reference_price IS DISTINCT FROM OLD.reference_price
       OR NEW.full_supply_price_multiplier IS DISTINCT FROM OLD.full_supply_price_multiplier
       OR NEW.curve_depth_shares IS DISTINCT FROM OLD.curve_depth_shares THEN
        IF NEW.net_shares_purchased <> 0 OR NEW.current_price <> NEW.reference_price THEN
            RAISE EXCEPTION
                'price curve rebase must reset net shares purchased and current price';
        END IF;
    ELSIF NEW.current_price IS DISTINCT FROM OLD.current_price
          AND NEW.net_shares_purchased IS NOT DISTINCT FROM OLD.net_shares_purchased THEN
        RAISE EXCEPTION
            'current price cannot change without advancing or rebasing the price curve';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TABLE index_funds (
    instrument_id uuid PRIMARY KEY REFERENCES instruments(id),
    -- TEAM: every league player at one club. Further kinds arrive with their own rules.
    index_kind text NOT NULL CHECK (index_kind IN ('TEAM')),
    club text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (index_kind <> 'TEAM' OR club IS NOT NULL)
);

CREATE UNIQUE INDEX index_funds_team_club_key
    ON index_funds (lower(club))
    WHERE index_kind = 'TEAM';

-- The basket behind one unit. Fixed after creation: changing it would leave the custody
-- account's holdings out of step with the units in issue.
CREATE TABLE index_constituents (
    index_instrument_id uuid NOT NULL REFERENCES index_funds(instrument_id),
    constituent_instrument_id uuid NOT NULL REFERENCES instruments(id),
    shares_per_unit numeric(18, 6) NOT NULL CHECK (shares_per_unit > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (index_instrument_id, constituent_instrument_id)
);

CREATE INDEX index_constituents_constituent_idx
    ON index_constituents (constituent_instrument_id);

-- The custody account's trade in each constituent points at the fund trade that caused it.
ALTER TABLE trades
    ADD COLUMN index_trade_id uuid REFERENCES trades(id);

CREATE INDEX trades_index_trade_id_idx
    ON trades (index_trade_id)
    WHERE index_trade_id IS NOT NULL;

-- A fund's price moves when a constituent trades; that snapshot links the constituent trade.
ALTER TABLE price_snapshots
    DROP CONSTRAINT price_snapshots_reason_check,
    ADD CONSTRAINT price_snapshots_reason_check CHECK (
        reason IN ('SEED', 'TRADE_BUY', 'TRADE_SELL', 'ADMIN_ADJUSTMENT', 'INDEX_REVALUATION')
    );
