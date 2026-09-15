CREATE TABLE social_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    external_source_id text NOT NULL,
    display_handle text,
    canonical_url text NOT NULL,
    source_category text NOT NULL,
    trust_weight numeric(5, 4) NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    policy_status text NOT NULL DEFAULT 'PENDING',
    terms_reviewed_at timestamptz NOT NULL,
    retention_days integer NOT NULL,
    approved_by text NOT NULL,
    approved_at timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, external_source_id),
    CHECK (provider IN ('TWITTER', 'BLUESKY', 'RSS', 'MASTODON')),
    CHECK (source_category IN (
        'OFFICIAL_LEAGUE', 'OFFICIAL_CLUB', 'PLAYER', 'JOURNALIST',
        'NEWS_ORGANISATION', 'COMMUNITY'
    )),
    CHECK (trust_weight >= 0 AND trust_weight <= 1),
    CHECK (policy_status IN ('PENDING', 'APPROVED', 'EXPIRED', 'REVOKED')),
    CHECK (retention_days >= 0),
    CHECK (NOT enabled OR policy_status = 'APPROVED')
);

CREATE TABLE social_subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES social_sources(id),
    provider text NOT NULL,
    mode text NOT NULL,
    configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
    polling_interval_seconds integer NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    next_eligible_poll_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (provider IN ('BLUESKY', 'RSS', 'MASTODON')),
    CHECK (mode IN ('AUTHOR_FEED', 'RSS_FEED', 'STREAM')),
    CHECK (polling_interval_seconds > 0)
);

CREATE INDEX social_subscriptions_due_idx
    ON social_subscriptions(next_eligible_poll_at)
    WHERE enabled = true;

CREATE TABLE social_ingestion_cursors (
    subscription_id uuid PRIMARY KEY REFERENCES social_subscriptions(id) ON DELETE CASCADE,
    cursor jsonb,
    etag text,
    last_modified text,
    last_polled_at timestamptz,
    last_success_at timestamptz,
    consecutive_failure_count integer NOT NULL DEFAULT 0,
    next_eligible_poll_at timestamptz,
    rate_limit_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_error_type text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (consecutive_failure_count >= 0)
);

CREATE TABLE social_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    external_id text NOT NULL,
    source_id uuid NOT NULL REFERENCES social_sources(id),
    subscription_id uuid REFERENCES social_subscriptions(id),
    document_kind text NOT NULL,
    author_external_id text,
    published_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    canonical_url text NOT NULL,
    language text,
    normalized_text text NOT NULL,
    content_hash text NOT NULL,
    provider_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    deleted_at timestamptz,
    UNIQUE (provider, external_id),
    CHECK (provider IN ('TWITTER', 'BLUESKY', 'RSS', 'MASTODON')),
    CHECK (document_kind IN ('POST', 'FEED_ENTRY'))
);

CREATE INDEX social_documents_source_published_idx
    ON social_documents(source_id, published_at DESC)
    WHERE deleted_at IS NULL;

CREATE TABLE social_document_processing_queue (
    document_id uuid PRIMARY KEY REFERENCES social_documents(id) ON DELETE CASCADE,
    available_at timestamptz NOT NULL DEFAULT now(),
    claimed_at timestamptz,
    processed_at timestamptz,
    failure_count integer NOT NULL DEFAULT 0,
    last_error text,
    CHECK (failure_count >= 0)
);

CREATE INDEX social_document_processing_pending_idx
    ON social_document_processing_queue(available_at, document_id)
    WHERE processed_at IS NULL;

CREATE TABLE social_injury_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES social_documents(id),
    classifier_version text NOT NULL,
    resolution_status text NOT NULL,
    player_id uuid REFERENCES players(id),
    resolution_confidence numeric(5, 4) NOT NULL,
    candidate_player_ids uuid[] NOT NULL DEFAULT '{}',
    matched_aliases text[] NOT NULL DEFAULT '{}',
    injury_classification text NOT NULL,
    classification_confidence numeric(5, 4) NOT NULL,
    availability_window_start timestamptz,
    availability_window_end timestamptz,
    evidence_status text NOT NULL,
    injury_episode_id uuid REFERENCES player_injury_episodes(id),
    invalidated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, classifier_version),
    CHECK (resolution_status IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED')),
    CHECK (resolution_confidence >= 0 AND resolution_confidence <= 1),
    CHECK (classification_confidence >= 0 AND classification_confidence <= 1),
    CHECK (evidence_status IN ('PENDING', 'ACTIONABLE', 'AGGREGATE_ONLY', 'REJECTED', 'INVALIDATED'))
);

CREATE INDEX social_injury_observations_unresolved_idx
    ON social_injury_observations(created_at)
    WHERE resolution_status <> 'RESOLVED' AND invalidated_at IS NULL;

CREATE TABLE social_player_injury_episode_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    injury_episode_id uuid NOT NULL REFERENCES player_injury_episodes(id),
    social_observation_id uuid NOT NULL UNIQUE REFERENCES social_injury_observations(id),
    social_source_id uuid NOT NULL REFERENCES social_sources(id),
    evidence_kind text NOT NULL,
    stage_before text,
    stage_after text NOT NULL,
    confidence numeric(5, 4) NOT NULL,
    observed_at timestamptz NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    invalidated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE TABLE player_social_signal_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id uuid NOT NULL REFERENCES players(id),
    calculated_at timestamptz NOT NULL,
    lookback_seconds integer NOT NULL,
    trusted_mention_count integer NOT NULL,
    credibility_weighted_sentiment numeric(7, 6),
    injury_confirmation_count integer NOT NULL,
    mention_velocity numeric(12, 6),
    corroborating_source_count integer NOT NULL,
    signal_confidence numeric(5, 4) NOT NULL,
    signal_age_seconds integer NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (player_id, calculated_at, lookback_seconds),
    CHECK (lookback_seconds > 0),
    CHECK (trusted_mention_count >= 0),
    CHECK (injury_confirmation_count >= 0),
    CHECK (corroborating_source_count >= 0),
    CHECK (signal_confidence >= 0 AND signal_confidence <= 1),
    CHECK (signal_age_seconds >= 0)
);

CREATE INDEX player_social_signal_snapshots_latest_idx
    ON player_social_signal_snapshots(player_id, calculated_at DESC, lookback_seconds);

-- Preserve reusable reviewed identities and audit metadata from the legacy source table.
INSERT INTO social_sources (
    provider, external_source_id, display_handle, canonical_url, source_category,
    trust_weight, enabled, policy_status, terms_reviewed_at, retention_days,
    approved_by, approved_at, metadata
)
SELECT
    'TWITTER', twitter_user_id, username, 'https://x.com/' || username,
    CASE account_kind
        WHEN 'PLAYER_OWNED' THEN 'PLAYER'
        WHEN 'CURATED_JOURNALIST' THEN 'JOURNALIST'
        WHEN 'FAN' THEN 'COMMUNITY'
        ELSE account_kind
    END,
    trust_weight, false, 'REVOKED', manually_reviewed_at, 0,
    reviewed_by, manually_reviewed_at,
    metadata || jsonb_build_object('legacy_source_id', id, 'review_notes', review_notes)
FROM twitter_injury_source_accounts
ON CONFLICT (provider, external_source_id) DO NOTHING;

-- Revocation and retention remove raw text and invalidate downstream evidence without
-- destroying the audit identity of the source or document.
CREATE OR REPLACE FUNCTION enforce_social_retention(as_of timestamptz DEFAULT now())
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE affected integer;
DECLARE expired_document_ids uuid[];
DECLARE affected_episode_ids uuid[];
BEGIN
    SELECT array_agg(document.id)
    INTO expired_document_ids
    FROM social_documents AS document
    JOIN social_sources AS source ON source.id = document.source_id
    WHERE document.deleted_at IS NULL
      AND (
          source.policy_status IN ('EXPIRED', 'REVOKED')
          OR document.ingested_at + make_interval(days => source.retention_days) <= as_of
      );

    IF expired_document_ids IS NULL THEN
        RETURN 0;
    END IF;

    UPDATE social_documents
    SET normalized_text = '', deleted_at = as_of
    WHERE id = ANY(expired_document_ids);
    GET DIAGNOSTICS affected = ROW_COUNT;

    SELECT array_agg(DISTINCT injury_episode_id)
    INTO affected_episode_ids
    FROM social_injury_observations
    WHERE document_id = ANY(expired_document_ids)
      AND injury_episode_id IS NOT NULL;

    UPDATE social_injury_observations AS observation
    SET evidence_status = 'INVALIDATED', invalidated_at = as_of, updated_at = now()
    WHERE observation.document_id = ANY(expired_document_ids)
      AND observation.invalidated_at IS NULL;

    UPDATE social_player_injury_episode_evidence AS evidence
    SET invalidated_at = as_of
    WHERE evidence.social_observation_id IN (
        SELECT id FROM social_injury_observations
        WHERE document_id = ANY(expired_document_ids)
    ) AND evidence.invalidated_at IS NULL;

    UPDATE player_injury_episodes AS episode
    SET expired_at = as_of, updated_at = now()
    WHERE affected_episode_ids IS NOT NULL
      AND episode.id = ANY(affected_episode_ids)
      AND episode.expired_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM social_player_injury_episode_evidence AS social_evidence
          WHERE social_evidence.injury_episode_id = episode.id
            AND social_evidence.invalidated_at IS NULL
      )
      AND NOT EXISTS (
          SELECT 1 FROM player_injury_episode_evidence AS legacy_evidence
          WHERE legacy_evidence.injury_episode_id = episode.id
      );

    RETURN affected;
END;
$$;
