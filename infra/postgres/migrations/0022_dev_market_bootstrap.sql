CREATE TABLE dev_market_bootstrap_instrument_valuations (
    instrument_id uuid PRIMARY KEY REFERENCES instruments(id),
    old_price numeric(18, 4) NOT NULL,
    new_price numeric(18, 4) NOT NULL,
    anchor_price numeric(18, 4) NOT NULL,
    market_rank double precision NOT NULL,
    stats_rank double precision NOT NULL,
    social_rank double precision NOT NULL,
    weights jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (old_price >= 0),
    CHECK (new_price > 0),
    CHECK (anchor_price > 0),
    CHECK (market_rank BETWEEN 0 AND 1),
    CHECK (stats_rank BETWEEN 0 AND 1),
    CHECK (social_rank BETWEEN 0 AND 1),
    CHECK (jsonb_typeof(weights) = 'object')
);

UPDATE instruments
SET current_price = CASE WHEN current_price <= 0 THEN 1.0000 ELSE current_price END,
    price_impact_unit = CASE
        WHEN price_impact_unit <= 0 THEN 0.000100
        ELSE price_impact_unit
    END,
    updated_at = now()
WHERE current_price <= 0 OR price_impact_unit <= 0;

ALTER TABLE instruments DROP CONSTRAINT IF EXISTS instruments_current_price_check;
ALTER TABLE instruments ADD CONSTRAINT instruments_current_price_check CHECK (current_price > 0);

ALTER TABLE instruments DROP CONSTRAINT IF EXISTS instruments_price_impact_unit_check;
ALTER TABLE instruments ADD CONSTRAINT instruments_price_impact_unit_check CHECK (price_impact_unit > 0);

ALTER TABLE player_market_value_observations
    ADD CONSTRAINT player_market_value_observations_positive_value_check CHECK (value > 0);
