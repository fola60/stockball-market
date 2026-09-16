-- Preserve enough precision for fractional-share execution and replace the
-- per-share linear price increment with persistent curve state.

ALTER TABLE instruments
    ALTER COLUMN current_price TYPE numeric(28, 12);

ALTER TABLE trades
    ALTER COLUMN execution_price TYPE numeric(28, 12),
    ALTER COLUMN gross_amount TYPE numeric(28, 12);

ALTER TABLE portfolios
    ALTER COLUMN cash_balance TYPE numeric(28, 12);

ALTER TABLE cash_ledger_entries
    ALTER COLUMN amount_delta TYPE numeric(28, 12),
    ALTER COLUMN balance_after TYPE numeric(28, 12);

ALTER TABLE price_snapshots
    ALTER COLUMN old_price TYPE numeric(28, 12),
    ALTER COLUMN new_price TYPE numeric(28, 12);

ALTER TABLE instruments
    ADD COLUMN reference_price numeric(28, 12),
    ADD COLUMN net_shares_purchased numeric(18, 6) NOT NULL DEFAULT 0,
    ADD COLUMN full_supply_price_multiplier numeric(10, 6) NOT NULL DEFAULT 2.500000;

UPDATE instruments
SET reference_price = current_price;

ALTER TABLE instruments
    ALTER COLUMN reference_price SET NOT NULL,
    ADD CONSTRAINT instruments_reference_price_check CHECK (reference_price > 0),
    ADD CONSTRAINT instruments_shares_outstanding_positive_check CHECK (shares_outstanding > 0),
    ADD CONSTRAINT instruments_net_shares_purchased_check CHECK (
        net_shares_purchased >= -shares_outstanding
        AND net_shares_purchased <= shares_outstanding
    ),
    ADD CONSTRAINT instruments_full_supply_price_multiplier_check CHECK (
        full_supply_price_multiplier > 1
    );

ALTER TABLE instruments
    DROP COLUMN price_impact_unit;

CREATE TABLE instrument_price_curve_rebases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id uuid NOT NULL REFERENCES instruments(id),
    old_reference_price numeric(28, 12) NOT NULL,
    new_reference_price numeric(28, 12) NOT NULL,
    old_full_supply_price_multiplier numeric(10, 6) NOT NULL,
    new_full_supply_price_multiplier numeric(10, 6) NOT NULL,
    old_net_shares_purchased numeric(18, 6) NOT NULL,
    changed_by text NOT NULL DEFAULT current_user,
    changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX instrument_price_curve_rebases_instrument_id_changed_at_idx
    ON instrument_price_curve_rebases(instrument_id, changed_at DESC);

CREATE FUNCTION enforce_instrument_price_curve_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.reference_price IS DISTINCT FROM OLD.reference_price
       OR NEW.full_supply_price_multiplier IS DISTINCT FROM OLD.full_supply_price_multiplier THEN
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

CREATE TRIGGER instruments_enforce_price_curve_update
BEFORE UPDATE OF current_price, reference_price, net_shares_purchased, full_supply_price_multiplier
ON instruments
FOR EACH ROW
EXECUTE FUNCTION enforce_instrument_price_curve_update();

CREATE FUNCTION record_instrument_price_curve_rebase()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.reference_price IS DISTINCT FROM OLD.reference_price
       OR NEW.full_supply_price_multiplier IS DISTINCT FROM OLD.full_supply_price_multiplier THEN
        INSERT INTO instrument_price_curve_rebases (
            instrument_id,
            old_reference_price,
            new_reference_price,
            old_full_supply_price_multiplier,
            new_full_supply_price_multiplier,
            old_net_shares_purchased
        ) VALUES (
            NEW.id,
            OLD.reference_price,
            NEW.reference_price,
            OLD.full_supply_price_multiplier,
            NEW.full_supply_price_multiplier,
            OLD.net_shares_purchased
        );
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER instruments_record_price_curve_rebase
AFTER UPDATE OF reference_price, full_supply_price_multiplier
ON instruments
FOR EACH ROW
EXECUTE FUNCTION record_instrument_price_curve_rebase();
