-- Trading fees, position cost basis, and the capital each portfolio has been given.
--
-- Every order now pays a fee on its gross amount, recorded on the trade and charged as its own
-- TRADE_FEE ledger entry. Positions carry their weighted-average cost basis, fees included, and
-- the profit or loss their sales locked in. Portfolios carry the capital they were given
-- (opening balance, top-ups, admin adjustments and issued shares), so performance can be
-- measured as a return on it rather than as raw net worth.

ALTER TABLE trades
    ADD COLUMN fee_amount numeric(28, 12) NOT NULL DEFAULT 0,
    ADD CONSTRAINT trades_fee_amount_check CHECK (fee_amount >= 0);

ALTER TABLE positions
    ADD COLUMN cost_basis numeric(28, 12) NOT NULL DEFAULT 0,
    ADD COLUMN realized_pnl numeric(28, 12) NOT NULL DEFAULT 0,
    ADD CONSTRAINT positions_cost_basis_check CHECK (cost_basis >= 0);

ALTER TABLE portfolios
    ADD COLUMN contributed_capital numeric(28, 12) NOT NULL DEFAULT 0;

ALTER TABLE cash_ledger_entries
    DROP CONSTRAINT cash_ledger_entries_reason_check,
    ADD CONSTRAINT cash_ledger_entries_reason_check CHECK (
        reason IN (
            'TRADE_BUY_DEBIT',
            'TRADE_SELL_CREDIT',
            'TRADE_FEE',
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
    ADD CONSTRAINT cash_ledger_entries_trade_fee_check CHECK (
        reason <> 'TRADE_FEE' OR amount_delta < 0
    );

-- Capital given so far: cash grants plus shares issued at their listing price.
UPDATE portfolios AS portfolio
SET contributed_capital = given.amount
FROM (
    SELECT portfolio_id, SUM(amount) AS amount
    FROM (
        SELECT portfolio_id, amount_delta AS amount
        FROM cash_ledger_entries
        WHERE reason IN ('OPENING_BALANCE', 'WEEKLY_TOPUP', 'MONTHLY_TOPUP', 'ADMIN_ADJUSTMENT')
        UNION ALL
        SELECT portfolio_id, quantity * seed_price
        FROM synthetic_portfolio_bootstrap_allocations
    ) AS grants
    GROUP BY portfolio_id
) AS given
WHERE given.portfolio_id = portfolio.id;

-- Rebuild each position's cost basis by replaying, in order, the shares it was issued, its
-- trades, and any delisting buyout. Past trades paid no fee, so their gross amount is their
-- cost or proceeds.
CREATE TEMP TABLE position_cost_replay (
    portfolio_id uuid NOT NULL,
    instrument_id uuid NOT NULL,
    quantity numeric NOT NULL DEFAULT 0,
    cost_basis numeric NOT NULL DEFAULT 0,
    realized_pnl numeric NOT NULL DEFAULT 0,
    PRIMARY KEY (portfolio_id, instrument_id)
);

DO $$
DECLARE
    event record;
    held record;
    sold numeric;
    removed numeric;
BEGIN
    FOR event IN
        SELECT *
        FROM (
            SELECT
                portfolio_id,
                instrument_id,
                'BUY'::text AS side,
                quantity::numeric AS shares,
                (quantity * seed_price)::numeric AS amount,
                created_at AS happened_at,
                0 AS sequence,
                id::text AS tiebreak
            FROM synthetic_portfolio_bootstrap_allocations
            UNION ALL
            SELECT
                portfolio_id,
                instrument_id,
                side,
                shares,
                gross_amount,
                executed_at,
                1,
                id::text
            FROM trades
            UNION ALL
            SELECT
                portfolio_id,
                split_part(source_request_id, ':', 2)::uuid,
                'BUYOUT',
                NULL,
                amount_delta,
                created_at,
                2,
                id::text
            FROM cash_ledger_entries
            WHERE reason = 'DELISTING_BUYOUT'
              AND source_request_id LIKE 'delisting:%:%'
        ) AS events
        ORDER BY happened_at, sequence, tiebreak
    LOOP
        INSERT INTO position_cost_replay (portfolio_id, instrument_id)
        VALUES (event.portfolio_id, event.instrument_id)
        ON CONFLICT DO NOTHING;

        IF event.side = 'BUY' THEN
            UPDATE position_cost_replay
            SET quantity = quantity + event.shares,
                cost_basis = cost_basis + event.amount
            WHERE portfolio_id = event.portfolio_id
              AND instrument_id = event.instrument_id;
        ELSE
            SELECT quantity, cost_basis INTO held
            FROM position_cost_replay
            WHERE portfolio_id = event.portfolio_id
              AND instrument_id = event.instrument_id;

            sold := COALESCE(event.shares, held.quantity);
            removed := CASE
                WHEN held.quantity <= 0 THEN 0
                WHEN sold >= held.quantity THEN held.cost_basis
                ELSE round(held.cost_basis * sold / held.quantity, 12)
            END;

            UPDATE position_cost_replay
            SET quantity = greatest(quantity - sold, 0),
                cost_basis = cost_basis - removed,
                realized_pnl = realized_pnl + event.amount - removed
            WHERE portfolio_id = event.portfolio_id
              AND instrument_id = event.instrument_id;
        END IF;
    END LOOP;
END $$;

-- A replay that matches the position is used as is. One that does not (positions created some
-- other way, such as a development seed) is scaled to the position, and a position the replay
-- never saw is valued at today's price.
UPDATE positions AS position
SET cost_basis = rebuilt.cost_basis,
    realized_pnl = rebuilt.realized_pnl
FROM (
    SELECT
        held.id,
        round(
            CASE
                WHEN held.quantity = 0 THEN 0
                WHEN replay.quantity = held.quantity THEN replay.cost_basis
                WHEN replay.quantity > 0 THEN replay.cost_basis * held.quantity / replay.quantity
                ELSE held.quantity * instrument.current_price
            END,
            12
        ) AS cost_basis,
        round(COALESCE(replay.realized_pnl, 0), 12) AS realized_pnl
    FROM positions AS held
    JOIN instruments AS instrument ON instrument.id = held.instrument_id
    LEFT JOIN position_cost_replay AS replay
        ON replay.portfolio_id = held.portfolio_id
       AND replay.instrument_id = held.instrument_id
) AS rebuilt
WHERE rebuilt.id = position.id;

DROP TABLE position_cost_replay;
