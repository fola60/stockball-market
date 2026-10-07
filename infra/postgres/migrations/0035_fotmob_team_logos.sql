-- Keep public FotMob club badges in Postgres, keyed by the source team ID.
-- Mirrors fotmob_player_images: missing badges and transient failures are retained
-- so scheduled runs back off instead of requesting the same badge on every poll.
CREATE TABLE fotmob_team_logos (
    provider_team_id text PRIMARY KEY,
    source_url text NOT NULL,
    status text NOT NULL CHECK (status IN ('READY', 'MISSING', 'FAILED')),
    image_data bytea,
    content_type text,
    content_sha256 text,
    width integer,
    height integer,
    fetched_at timestamptz,
    last_attempt_at timestamptz NOT NULL DEFAULT now(),
    next_fetch_at timestamptz NOT NULL DEFAULT now(),
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (status = 'READY') =
        (image_data IS NOT NULL AND content_type = 'image/png'
         AND content_sha256 IS NOT NULL AND width IS NOT NULL
         AND height IS NOT NULL AND fetched_at IS NOT NULL)
    ),
    CHECK (image_data IS NULL OR octet_length(image_data) <= 1048576),
    CHECK (width IS NULL OR width BETWEEN 1 AND 4096),
    CHECK (height IS NULL OR height BETWEEN 1 AND 4096)
);
CREATE INDEX fotmob_team_logos_next_fetch_idx
    ON fotmob_team_logos(next_fetch_at, provider_team_id);
