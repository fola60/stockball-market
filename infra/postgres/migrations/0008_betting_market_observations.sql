CREATE TABLE betting_market_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fixture_id uuid REFERENCES fixtures(id),
    provider text NOT NULL,
    provider_event_id text NOT NULL,
    fixture_provider_id text,
    market_key text NOT NULL,
    selection_key text NOT NULL,
    decimal_odds numeric(12, 6) NOT NULL CHECK (decimal_odds > 1),
    implied_probability numeric(12, 8) NOT NULL CHECK (implied_probability > 0 AND implied_probability < 1),
    observed_at timestamptz NOT NULL,
    source_url text,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_event_id, market_key, selection_key, observed_at)
);

CREATE INDEX betting_market_observations_fixture_observed_idx
    ON betting_market_observations(fixture_id, observed_at DESC)
    WHERE fixture_id IS NOT NULL;

CREATE INDEX betting_market_observations_provider_event_observed_idx
    ON betting_market_observations(provider, provider_event_id, observed_at DESC);
