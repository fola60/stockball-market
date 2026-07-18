CREATE TABLE twitter_injury_source_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    twitter_user_id text NOT NULL UNIQUE,
    username text NOT NULL,
    display_name text NOT NULL,
    account_kind text NOT NULL,
    trust_weight numeric(4, 3) NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    manually_reviewed_at timestamptz NOT NULL,
    reviewed_by text NOT NULL,
    review_notes text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        account_kind IN (
            'OFFICIAL_CLUB',
            'OFFICIAL_LEAGUE',
            'PLAYER_OWNED',
            'CURATED_JOURNALIST',
            'FAN'
        )
    ),
    CHECK (trust_weight > 0 AND trust_weight <= 1),
    CHECK (
        account_kind NOT IN ('OFFICIAL_CLUB', 'OFFICIAL_LEAGUE', 'PLAYER_OWNED')
        OR trust_weight = 1.000
    ),
    CHECK (
        account_kind <> 'CURATED_JOURNALIST'
        OR trust_weight <= 0.950
    ),
    CHECK (account_kind <> 'FAN' OR trust_weight <= 0.400)
);

CREATE UNIQUE INDEX twitter_injury_source_accounts_username_key
    ON twitter_injury_source_accounts(lower(username));

CREATE TABLE twitter_player_aliases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id uuid NOT NULL REFERENCES players(id),
    alias text NOT NULL,
    normalized_alias text NOT NULL,
    alias_type text NOT NULL,
    club_hint text,
    manually_reviewed_at timestamptz NOT NULL,
    reviewed_by text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (player_id, normalized_alias),
    CHECK (alias_type IN ('NAME', 'HANDLE', 'NICKNAME'))
);

CREATE INDEX twitter_player_aliases_normalized_alias_idx
    ON twitter_player_aliases(normalized_alias)
    WHERE enabled = true;

CREATE TABLE twitter_injury_ingestion_cursors (
    query_key text PRIMARY KEY,
    query text NOT NULL,
    since_id text,
    next_token text,
    pending_newest_id text,
    rate_limit_limit integer,
    rate_limit_remaining integer,
    rate_limit_reset_at timestamptz,
    last_polled_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE twitter_injury_posts (
    twitter_post_id text PRIMARY KEY,
    twitter_author_id text NOT NULL,
    source_account_id uuid NOT NULL REFERENCES twitter_injury_source_accounts(id),
    posted_at timestamptz NOT NULL,
    lang text,
    raw_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE INDEX twitter_injury_posts_source_posted_idx
    ON twitter_injury_posts(source_account_id, posted_at DESC)
    WHERE deleted_at IS NULL;

CREATE TABLE player_injury_episodes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id uuid NOT NULL REFERENCES players(id),
    recurrence_of_episode_id uuid REFERENCES player_injury_episodes(id),
    stage text NOT NULL,
    injury_type text,
    body_area text,
    confidence numeric(5, 4) NOT NULL,
    started_at timestamptz NOT NULL,
    last_evidence_at timestamptz NOT NULL,
    expected_absence_until timestamptz,
    recovered_at timestamptz,
    expires_at timestamptz NOT NULL,
    expired_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        stage IN (
            'SUSPECTED_INJURY',
            'CONFIRMED_INJURY',
            'SUSPECTED_RECOVERY',
            'CONFIRMED_RECOVERED'
        )
    ),
    CHECK (confidence >= 0 AND confidence <= 1),
    CHECK (
        stage <> 'CONFIRMED_RECOVERED'
        OR recovered_at IS NOT NULL
    )
);

CREATE UNIQUE INDEX player_injury_episodes_one_active_idx
    ON player_injury_episodes(player_id)
    WHERE expired_at IS NULL AND stage <> 'CONFIRMED_RECOVERED';

CREATE INDEX player_injury_episodes_player_started_idx
    ON player_injury_episodes(player_id, started_at DESC);

CREATE INDEX player_injury_episodes_expiry_idx
    ON player_injury_episodes(expires_at)
    WHERE expired_at IS NULL AND stage <> 'CONFIRMED_RECOVERED';

CREATE TABLE twitter_injury_post_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    twitter_post_id text NOT NULL UNIQUE REFERENCES twitter_injury_posts(twitter_post_id),
    resolution_status text NOT NULL,
    player_id uuid REFERENCES players(id),
    candidate_player_ids uuid[] NOT NULL DEFAULT '{}',
    matched_aliases text[] NOT NULL DEFAULT '{}',
    resolution_reason text NOT NULL,
    evidence_kind text NOT NULL,
    confidence numeric(5, 4) NOT NULL,
    injury_type text,
    body_area text,
    absence_min_days integer,
    absence_max_days integer,
    negated boolean NOT NULL DEFAULT false,
    uncertain boolean NOT NULL DEFAULT false,
    aggregate_only boolean NOT NULL DEFAULT false,
    matched_rules text[] NOT NULL DEFAULT '{}',
    episode_id uuid REFERENCES player_injury_episodes(id),
    processed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (resolution_status IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED')),
    CHECK (
        evidence_kind IN (
            'NONE',
            'SUSPECTED_INJURY',
            'CONFIRMED_INJURY',
            'RETURN_TO_TRAINING',
            'SQUAD_RETURN',
            'OFFICIAL_RECOVERY',
            'MATCH_PARTICIPATION'
        )
    ),
    CHECK (confidence >= 0 AND confidence <= 1),
    CHECK (absence_min_days IS NULL OR absence_min_days >= 0),
    CHECK (absence_max_days IS NULL OR absence_max_days >= absence_min_days)
);

CREATE INDEX twitter_injury_post_observations_player_created_idx
    ON twitter_injury_post_observations(player_id, created_at DESC)
    WHERE player_id IS NOT NULL;

CREATE VIEW player_twitter_injury_fan_signal_daily AS
SELECT
    observation.player_id,
    date_trunc('day', post.posted_at) AS observed_day,
    COUNT(*) AS mention_count,
    AVG(observation.confidence) AS average_confidence,
    MAX(observation.confidence) AS maximum_confidence,
    COUNT(*) FILTER (
        WHERE observation.evidence_kind IN ('SUSPECTED_INJURY', 'CONFIRMED_INJURY')
    ) AS injury_evidence_count,
    COUNT(*) FILTER (
        WHERE observation.evidence_kind IN (
            'RETURN_TO_TRAINING',
            'SQUAD_RETURN',
            'OFFICIAL_RECOVERY',
            'MATCH_PARTICIPATION'
        )
    ) AS recovery_evidence_count
FROM twitter_injury_post_observations AS observation
JOIN twitter_injury_posts AS post
    ON post.twitter_post_id = observation.twitter_post_id
WHERE observation.aggregate_only = true
  AND observation.resolution_status = 'RESOLVED'
  AND observation.player_id IS NOT NULL
  AND post.deleted_at IS NULL
GROUP BY observation.player_id, date_trunc('day', post.posted_at);

CREATE TABLE player_injury_episode_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    injury_episode_id uuid NOT NULL REFERENCES player_injury_episodes(id),
    post_observation_id uuid REFERENCES twitter_injury_post_observations(id),
    fixture_id uuid REFERENCES fixtures(id),
    source_account_id uuid REFERENCES twitter_injury_source_accounts(id),
    evidence_kind text NOT NULL,
    stage_before text,
    stage_after text NOT NULL,
    confidence numeric(5, 4) NOT NULL,
    observed_at timestamptz NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        evidence_kind IN (
            'SUSPECTED_INJURY',
            'CONFIRMED_INJURY',
            'RETURN_TO_TRAINING',
            'SQUAD_RETURN',
            'OFFICIAL_RECOVERY',
            'MATCH_PARTICIPATION'
        )
    ),
    CHECK (
        stage_after IN (
            'SUSPECTED_INJURY',
            'CONFIRMED_INJURY',
            'SUSPECTED_RECOVERY',
            'CONFIRMED_RECOVERED'
        )
    ),
    CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE UNIQUE INDEX player_injury_episode_evidence_post_key
    ON player_injury_episode_evidence(post_observation_id)
    WHERE post_observation_id IS NOT NULL;

CREATE UNIQUE INDEX player_injury_episode_evidence_fixture_key
    ON player_injury_episode_evidence(injury_episode_id, fixture_id, evidence_kind)
    WHERE fixture_id IS NOT NULL;

CREATE TABLE player_injury_availability_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id uuid NOT NULL REFERENCES players(id),
    injury_episode_id uuid NOT NULL REFERENCES player_injury_episodes(id),
    stage text NOT NULL,
    confidence numeric(5, 4) NOT NULL,
    is_available boolean NOT NULL,
    expected_absence_until timestamptz,
    injury_type text,
    body_area text,
    evidence_kind text NOT NULL,
    source_account_kind text,
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        stage IN (
            'SUSPECTED_INJURY',
            'CONFIRMED_INJURY',
            'SUSPECTED_RECOVERY',
            'CONFIRMED_RECOVERED'
        )
    ),
    CHECK (confidence >= 0 AND confidence <= 1),
    CHECK (is_available = (stage = 'CONFIRMED_RECOVERED'))
);

CREATE INDEX player_injury_availability_player_observed_idx
    ON player_injury_availability_observations(player_id, observed_at DESC);

CREATE VIEW player_current_injury_availability AS
SELECT DISTINCT ON (observation.player_id)
    observation.player_id,
    observation.injury_episode_id,
    observation.stage,
    observation.confidence,
    observation.is_available,
    observation.expected_absence_until,
    observation.injury_type,
    observation.body_area,
    observation.evidence_kind,
    observation.source_account_kind,
    observation.observed_at
FROM player_injury_availability_observations AS observation
JOIN player_injury_episodes AS episode
    ON episode.id = observation.injury_episode_id
WHERE episode.expired_at IS NULL
ORDER BY
    observation.player_id,
    observation.observed_at DESC,
    observation.created_at DESC,
    observation.id DESC;
