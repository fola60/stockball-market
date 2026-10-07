-- Curve depth: the net shares that carry a price all the way to its full-supply multiplier.
-- Until now that depth was always the full supply, almost all of it held in reserve, so trades
-- barely moved prices. Every instrument starts at its full supply, which changes nothing; the
-- trading engine's curve recalibration then sets a shallower depth through a rebase.

ALTER TABLE instruments
    ADD COLUMN curve_depth_shares numeric(18, 6);

UPDATE instruments
SET curve_depth_shares = shares_outstanding;

ALTER TABLE instruments
    ALTER COLUMN curve_depth_shares SET NOT NULL,
    ADD CONSTRAINT instruments_curve_depth_shares_check CHECK (
        curve_depth_shares > 0
        AND curve_depth_shares <= shares_outstanding
    ),
    -- Net demand is bounded by the curve, which may now be shallower than the supply.
    DROP CONSTRAINT instruments_net_shares_purchased_check,
    ADD CONSTRAINT instruments_net_shares_purchased_check CHECK (
        net_shares_purchased >= -curve_depth_shares
        AND net_shares_purchased <= curve_depth_shares
    );

-- An instrument inserted without a depth spans its full supply, the curve it had before.
CREATE FUNCTION default_instrument_curve_depth()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.curve_depth_shares IS NULL THEN
        NEW.curve_depth_shares := NEW.shares_outstanding;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER instruments_default_curve_depth
BEFORE INSERT ON instruments
FOR EACH ROW
EXECUTE FUNCTION default_instrument_curve_depth();

ALTER TABLE instrument_price_curve_rebases
    ADD COLUMN old_curve_depth_shares numeric(18, 6),
    ADD COLUMN new_curve_depth_shares numeric(18, 6);

-- A depth change re-anchors the curve exactly like a multiplier change: net demand resets and
-- the reference becomes the current price, so no price moves without a trade.
CREATE OR REPLACE FUNCTION enforce_instrument_price_curve_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
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

DROP TRIGGER instruments_enforce_price_curve_update ON instruments;
CREATE TRIGGER instruments_enforce_price_curve_update
BEFORE UPDATE OF current_price, reference_price, net_shares_purchased,
    full_supply_price_multiplier, curve_depth_shares
ON instruments
FOR EACH ROW
EXECUTE FUNCTION enforce_instrument_price_curve_update();

CREATE OR REPLACE FUNCTION record_instrument_price_curve_rebase()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.reference_price IS DISTINCT FROM OLD.reference_price
       OR NEW.full_supply_price_multiplier IS DISTINCT FROM OLD.full_supply_price_multiplier
       OR NEW.curve_depth_shares IS DISTINCT FROM OLD.curve_depth_shares THEN
        INSERT INTO instrument_price_curve_rebases (
            instrument_id,
            old_reference_price,
            new_reference_price,
            old_full_supply_price_multiplier,
            new_full_supply_price_multiplier,
            old_net_shares_purchased,
            old_curve_depth_shares,
            new_curve_depth_shares
        ) VALUES (
            NEW.id,
            OLD.reference_price,
            NEW.reference_price,
            OLD.full_supply_price_multiplier,
            NEW.full_supply_price_multiplier,
            OLD.net_shares_purchased,
            OLD.curve_depth_shares,
            NEW.curve_depth_shares
        );
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER instruments_record_price_curve_rebase ON instruments;
CREATE TRIGGER instruments_record_price_curve_rebase
AFTER UPDATE OF reference_price, full_supply_price_multiplier, curve_depth_shares
ON instruments
FOR EACH ROW
EXECUTE FUNCTION record_instrument_price_curve_rebase();
