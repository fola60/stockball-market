ALTER TABLE fixtures
    ADD COLUMN competition text,
    ADD COLUMN source_url text,
    ADD COLUMN provider_match_id text;

CREATE INDEX fixtures_provider_match_id_idx
    ON fixtures(provider, provider_match_id)
    WHERE provider_match_id IS NOT NULL;

ALTER TABLE player_stat_observations
    ADD COLUMN stat_type text,
    ADD COLUMN season integer,
    ADD COLUMN competition text,
    ADD COLUMN source_url text;

CREATE INDEX player_stat_observations_provider_season_stat_idx
    ON player_stat_observations(provider, season, stat_type);

CREATE TABLE provider_raw_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    source_url text NOT NULL,
    content_hash text NOT NULL,
    body text NOT NULL,
    status_code integer NOT NULL,
    content_type text,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, source_url, content_hash)
);

CREATE INDEX provider_raw_documents_provider_url_seen_idx
    ON provider_raw_documents(provider, source_url, fetched_at DESC);
