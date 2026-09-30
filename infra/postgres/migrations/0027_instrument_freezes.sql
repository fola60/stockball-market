-- Records why an instrument is frozen. An instrument's trading_status is FROZEN while it has
-- at least one open freeze, so releasing a match-day freeze cannot lift an admin halt.
CREATE TABLE instrument_freezes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id uuid NOT NULL REFERENCES instruments(id),
    reason text NOT NULL CHECK (reason IN ('MATCH_DAY', 'ADMIN_HALT', 'DATA_ISSUE')),
    -- Identifies what the freeze is for, e.g. `fixture:<uuid>` for a match-day freeze. Every
    -- open freeze with the same source key is released together.
    source_key text NOT NULL CHECK (length(source_key) > 0),
    started_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,
    CHECK (released_at IS NULL OR released_at >= started_at)
);

CREATE UNIQUE INDEX instrument_freezes_open_key
    ON instrument_freezes (instrument_id, source_key)
    WHERE released_at IS NULL;

CREATE INDEX instrument_freezes_open_source_idx
    ON instrument_freezes (source_key)
    WHERE released_at IS NULL;

-- Instruments frozen before freeze records existed keep their status under an admin halt, so
-- they are released explicitly rather than by a match-day job.
INSERT INTO instrument_freezes (instrument_id, reason, source_key)
SELECT id, 'ADMIN_HALT', 'legacy-freeze'
FROM instruments
WHERE trading_status = 'FROZEN';
