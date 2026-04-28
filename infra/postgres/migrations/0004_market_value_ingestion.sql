CREATE TABLE player_provider_refs (
    player_id uuid NOT NULL REFERENCES players(id),
    provider text NOT NULL,
    provider_player_id text NOT NULL,
    provider_url text,
    confidence numeric(4, 3),
    is_primary boolean NOT NULL DEFAULT false,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    raw_identity jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (provider, provider_player_id)
);

CREATE INDEX player_provider_refs_player_id_idx
    ON player_provider_refs(player_id);

CREATE TYPE market_value_match_status AS ENUM (
    'UNMATCHED',
    'MATCHED',
    'AMBIGUOUS',
    'REJECTED'
);

CREATE TABLE market_value_import_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL,
    players_csv_path text,
    valuations_csv_path text NOT NULL,
    status text NOT NULL DEFAULT 'STARTED',
    imported_rows integer NOT NULL DEFAULT 0,
    matched_rows integer NOT NULL DEFAULT 0,
    ambiguous_rows integer NOT NULL DEFAULT 0,
    unmatched_rows integer NOT NULL DEFAULT 0,
    rejected_rows integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CHECK (status IN ('STARTED', 'COMPLETED', 'FAILED'))
);

CREATE TABLE market_value_import_rows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_batch_id uuid NOT NULL REFERENCES market_value_import_batches(id),
    source text NOT NULL,
    source_player_id text NOT NULL,
    source_player_name text,
    source_club text,
    source_date_of_birth date,
    source_nationality text,
    value numeric(20, 4) NOT NULL,
    currency text NOT NULL,
    observed_at timestamptz NOT NULL,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    matched_player_id uuid REFERENCES players(id),
    match_status market_value_match_status NOT NULL,
    match_confidence numeric(4, 3),
    match_reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX market_value_import_rows_batch_idx
    ON market_value_import_rows(import_batch_id);

CREATE INDEX market_value_import_rows_status_idx
    ON market_value_import_rows(match_status);

CREATE INDEX market_value_import_rows_source_player_idx
    ON market_value_import_rows(source, source_player_id);

CREATE TABLE player_market_value_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id uuid NOT NULL REFERENCES players(id),
    source text NOT NULL,
    source_player_id text NOT NULL,
    value numeric(20, 4) NOT NULL,
    currency text NOT NULL,
    observed_at timestamptz NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (player_id, source, source_player_id, observed_at)
);

CREATE INDEX player_market_value_observations_player_observed_idx
    ON player_market_value_observations(player_id, observed_at DESC);

CREATE INDEX player_market_value_observations_source_player_idx
    ON player_market_value_observations(source, source_player_id);
