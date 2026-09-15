CREATE TABLE social_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES social_documents(id),
    classifier_version text NOT NULL,
    resolution_status text NOT NULL,
    entity_type text NOT NULL,
    player_id uuid REFERENCES players(id),
    team_name text,
    resolution_confidence numeric(5, 4) NOT NULL,
    candidate_player_ids uuid[] NOT NULL DEFAULT '{}',
    matched_aliases text[] NOT NULL DEFAULT '{}',
    topic text NOT NULL,
    sentiment text NOT NULL,
    sentiment_score numeric(7, 6) NOT NULL,
    classification_confidence numeric(5, 4) NOT NULL,
    observation_status text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    invalidated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, classifier_version),
    CHECK (resolution_status IN ('RESOLVED', 'AMBIGUOUS', 'UNRESOLVED')),
    CHECK (entity_type IN ('PLAYER', 'TEAM', 'UNKNOWN')),
    CHECK (topic IN ('GENERAL', 'PERFORMANCE', 'SELECTION', 'TRANSFER', 'INJURY', 'RECOVERY')),
    CHECK (sentiment IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL', 'MIXED')),
    CHECK (sentiment_score >= -1 AND sentiment_score <= 1),
    CHECK (resolution_confidence >= 0 AND resolution_confidence <= 1),
    CHECK (classification_confidence >= 0 AND classification_confidence <= 1),
    CHECK (observation_status IN (
        'INCLUDED', 'AGGREGATE_ONLY', 'AMBIGUOUS', 'UNRESOLVED',
        'REJECTED', 'INVALIDATED'
    )),
    CHECK (
        (entity_type = 'PLAYER' AND player_id IS NOT NULL AND team_name IS NULL)
        OR (entity_type = 'TEAM' AND player_id IS NULL AND team_name IS NOT NULL)
        OR (entity_type = 'UNKNOWN' AND player_id IS NULL AND team_name IS NULL)
    )
);

CREATE INDEX social_observations_player_published_idx
    ON social_observations(player_id, created_at DESC)
    WHERE player_id IS NOT NULL AND invalidated_at IS NULL;

CREATE INDEX social_observations_topic_sentiment_idx
    ON social_observations(topic, sentiment, created_at DESC)
    WHERE invalidated_at IS NULL;

-- Preserve all previously processed documents as general observations. They are reclassified
-- by the application when replayed; this backfill provides safe neutral/injury defaults now.
INSERT INTO social_observations (
    document_id,
    classifier_version,
    resolution_status,
    entity_type,
    player_id,
    team_name,
    resolution_confidence,
    candidate_player_ids,
    matched_aliases,
    topic,
    sentiment,
    sentiment_score,
    classification_confidence,
    observation_status,
    metadata,
    invalidated_at,
    created_at,
    updated_at
)
SELECT
    injury.document_id,
    'general-rules-v1',
    injury.resolution_status,
    CASE
        WHEN injury.player_id IS NOT NULL THEN 'PLAYER'
        WHEN injury.resolution_status = 'UNRESOLVED'
         AND NULLIF(BTRIM(source.metadata->>'club'), '') IS NOT NULL THEN 'TEAM'
        ELSE 'UNKNOWN'
    END,
    injury.player_id,
    CASE
        WHEN injury.player_id IS NULL
         AND injury.resolution_status = 'UNRESOLVED'
        THEN NULLIF(BTRIM(source.metadata->>'club'), '')
        ELSE NULL
    END,
    injury.resolution_confidence,
    injury.candidate_player_ids,
    injury.matched_aliases,
    CASE
        WHEN injury.injury_classification IN ('SUSPECTED_INJURY', 'CONFIRMED_INJURY')
        THEN 'INJURY'
        WHEN injury.injury_classification IN (
            'RETURN_TO_TRAINING', 'SQUAD_RETURN', 'OFFICIAL_RECOVERY', 'MATCH_PARTICIPATION'
        ) THEN 'RECOVERY'
        ELSE 'GENERAL'
    END,
    CASE
        WHEN injury.injury_classification IN ('SUSPECTED_INJURY', 'CONFIRMED_INJURY')
        THEN 'NEGATIVE'
        WHEN injury.injury_classification IN (
            'RETURN_TO_TRAINING', 'SQUAD_RETURN', 'OFFICIAL_RECOVERY', 'MATCH_PARTICIPATION'
        ) THEN 'POSITIVE'
        ELSE 'NEUTRAL'
    END,
    CASE
        WHEN injury.injury_classification IN ('SUSPECTED_INJURY', 'CONFIRMED_INJURY')
        THEN -1
        WHEN injury.injury_classification IN (
            'RETURN_TO_TRAINING', 'SQUAD_RETURN', 'OFFICIAL_RECOVERY', 'MATCH_PARTICIPATION'
        ) THEN 1
        ELSE 0
    END,
    GREATEST(0.5, injury.classification_confidence),
    CASE
        WHEN injury.invalidated_at IS NOT NULL THEN 'INVALIDATED'
        WHEN NOT source.enabled OR source.policy_status <> 'APPROVED' THEN 'REJECTED'
        WHEN injury.resolution_status = 'AMBIGUOUS' THEN 'AMBIGUOUS'
        WHEN injury.player_id IS NULL
         AND NULLIF(BTRIM(source.metadata->>'club'), '') IS NULL THEN 'UNRESOLVED'
        WHEN source.source_category = 'COMMUNITY' THEN 'AGGREGATE_ONLY'
        ELSE 'INCLUDED'
    END,
    jsonb_build_object('backfilled_from_injury_observation', injury.id),
    injury.invalidated_at,
    injury.created_at,
    injury.updated_at
FROM social_injury_observations AS injury
JOIN social_documents AS document ON document.id = injury.document_id
JOIN social_sources AS source ON source.id = document.source_id
ON CONFLICT (document_id, classifier_version) DO NOTHING;

ALTER TABLE social_injury_observations
    ADD COLUMN social_observation_id uuid REFERENCES social_observations(id);

UPDATE social_injury_observations AS injury
SET social_observation_id = observation.id
FROM social_observations AS observation
WHERE observation.document_id = injury.document_id
  AND observation.classifier_version = 'general-rules-v1';

CREATE UNIQUE INDEX social_injury_observations_general_idx
    ON social_injury_observations(social_observation_id)
    WHERE social_observation_id IS NOT NULL;

ALTER TABLE social_player_injury_episode_evidence
    RENAME COLUMN social_observation_id TO social_injury_observation_id;

-- Retention now invalidates both general and injury-specific observations.
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

    UPDATE social_observations AS observation
    SET observation_status = 'INVALIDATED', invalidated_at = as_of, updated_at = now()
    WHERE observation.document_id = ANY(expired_document_ids)
      AND observation.invalidated_at IS NULL;

    UPDATE social_injury_observations AS injury
    SET evidence_status = 'INVALIDATED', invalidated_at = as_of, updated_at = now()
    WHERE injury.document_id = ANY(expired_document_ids)
      AND injury.invalidated_at IS NULL;

    UPDATE social_player_injury_episode_evidence AS evidence
    SET invalidated_at = as_of
    WHERE evidence.social_injury_observation_id IN (
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
