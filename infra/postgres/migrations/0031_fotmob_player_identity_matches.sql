-- Persist the same identity decisions used by market-value ingestion for review.
CREATE TABLE fotmob_player_identity_matches (
    provider_player_id text PRIMARY KEY,
    player_id uuid REFERENCES players(id),
    match_status text NOT NULL CHECK (match_status IN ('MATCHED', 'AMBIGUOUS', 'UNMATCHED')),
    match_confidence numeric(4, 3),
    match_reason text NOT NULL,
    source_names text[] NOT NULL,
    source_clubs text[] NOT NULL,
    evidence jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((match_status = 'MATCHED') = (player_id IS NOT NULL)),
    CHECK ((match_status = 'MATCHED') = (match_confidence IS NOT NULL))
);
CREATE INDEX fotmob_player_identity_matches_status_idx
    ON fotmob_player_identity_matches(match_status, updated_at DESC);
