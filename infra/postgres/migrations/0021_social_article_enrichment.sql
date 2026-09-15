-- Durable, policy-gated article-body enrichment for trusted RSS publishers.

ALTER TABLE social_documents
    ADD COLUMN source_text text,
    ADD COLUMN enriched_text text;

UPDATE social_documents
SET source_text = normalized_text
WHERE source_text IS NULL;

ALTER TABLE social_documents
    ALTER COLUMN source_text SET NOT NULL;

CREATE TABLE social_document_enrichments (
    document_id uuid PRIMARY KEY REFERENCES social_documents(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'PENDING',
    available_at timestamptz NOT NULL DEFAULT now(),
    claimed_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0,
    completed_at timestamptz,
    final_url text,
    http_status integer,
    extraction_method text,
    extracted_characters integer,
    last_error text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('PENDING', 'SUCCEEDED', 'SKIPPED', 'FAILED')),
    CHECK (attempt_count >= 0),
    CHECK (extracted_characters IS NULL OR extracted_characters >= 0)
);

CREATE INDEX social_document_enrichments_pending_idx
    ON social_document_enrichments(available_at, document_id)
    WHERE status = 'PENDING';

-- Only explicit, reviewed news hosts are eligible. Community feeds remain summary-only.
UPDATE social_sources
SET metadata = jsonb_set(
        metadata,
        '{article_enrichment}',
        jsonb_build_object(
            'enabled', true,
            'allowed_hosts', CASE
                WHEN canonical_url LIKE 'https://www.bbc.%'
                    THEN to_jsonb(ARRAY['www.bbc.com', 'www.bbc.co.uk', 'bbc.com', 'bbc.co.uk'])
                WHEN canonical_url LIKE 'https://www.theguardian.com/%'
                    THEN to_jsonb(ARRAY['www.theguardian.com', 'theguardian.com'])
                WHEN canonical_url LIKE 'https://www.skysports.com/%'
                    THEN to_jsonb(ARRAY['www.skysports.com', 'skysports.com'])
                WHEN canonical_url LIKE 'https://www.espn.com/%'
                    THEN to_jsonb(ARRAY['www.espn.com', 'espn.com'])
                WHEN canonical_url LIKE 'https://www.theargus.co.uk/%'
                    THEN to_jsonb(ARRAY['www.theargus.co.uk', 'theargus.co.uk'])
                WHEN canonical_url LIKE 'https://www.coventrytelegraph.net/%'
                    THEN to_jsonb(ARRAY['www.coventrytelegraph.net', 'coventrytelegraph.net'])
                WHEN canonical_url LIKE 'https://www.hulldailymail.co.uk/%'
                    THEN to_jsonb(ARRAY['www.hulldailymail.co.uk', 'hulldailymail.co.uk'])
                WHEN canonical_url LIKE 'https://www.lemonde.fr/%'
                    THEN to_jsonb(ARRAY['www.lemonde.fr', 'lemonde.fr'])
                ELSE '[]'::jsonb
            END,
            'max_article_bytes', 1500000,
            'reviewed_at', '2026-09-12T00:00:00Z'
        ),
        true
    ),
    updated_at = now()
WHERE provider = 'RSS'
  AND enabled
  AND policy_status = 'APPROVED'
  AND source_category = 'NEWS_ORGANISATION'
  AND (
      canonical_url LIKE 'https://www.bbc.%'
      OR canonical_url LIKE 'https://www.theguardian.com/%'
      OR canonical_url LIKE 'https://www.skysports.com/%'
      OR canonical_url LIKE 'https://www.espn.com/%'
      OR canonical_url LIKE 'https://www.theargus.co.uk/%'
      OR canonical_url LIKE 'https://www.coventrytelegraph.net/%'
      OR canonical_url LIKE 'https://www.hulldailymail.co.uk/%'
      OR canonical_url LIKE 'https://www.lemonde.fr/%'
  );

-- Queue retained existing documents so deployments gain enrichment without re-ingesting feeds.
INSERT INTO social_document_enrichments (document_id)
SELECT document.id
FROM social_documents document
JOIN social_sources source ON source.id = document.source_id
WHERE document.provider = 'RSS'
  AND document.document_kind = 'FEED_ENTRY'
  AND document.deleted_at IS NULL
  AND source.enabled
  AND source.policy_status = 'APPROVED'
  AND COALESCE((source.metadata->'article_enrichment'->>'enabled')::boolean, false)
ON CONFLICT (document_id) DO NOTHING;

-- Retention must clear both original and enriched raw text.
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
    SET normalized_text = '', source_text = '', enriched_text = NULL, deleted_at = as_of
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
