CREATE TABLE betting_market_selections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fixture_id uuid REFERENCES fixtures(id),
    provider text NOT NULL,
    provider_event_id text NOT NULL,
    fixture_provider_id text,
    market_scope text NOT NULL,
    market_type text NOT NULL,
    period text NOT NULL DEFAULT 'FULL_MATCH',
    outcome_type text NOT NULL,
    line numeric(12, 4),
    canonical_selection_key text NOT NULL,
    provider_market_label text NOT NULL,
    provider_selection_label text NOT NULL,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (market_scope IN ('MATCH', 'TEAM', 'PLAYER', 'PLAYER_PAIR')),
    CHECK (
        market_type IN (
            'MATCH_RESULT_1X2', 'GOALSCORER', 'ASSIST', 'SCORE_OR_ASSIST',
            'SHOTS', 'SHOTS_ON_TARGET', 'FOULS_COMMITTED', 'FOULS_DRAWN',
            'CARD', 'EITHER_TO_SCORE', 'EITHER_TO_ASSIST',
            'EITHER_TO_SCORE_OR_ASSIST'
        )
    ),
    CHECK (period IN ('FULL_MATCH', 'FIRST_HALF', 'SECOND_HALF')),
    CHECK (
        outcome_type IN (
            'HOME', 'DRAW', 'AWAY', 'ANYTIME', 'FIRST', 'LAST',
            'OVER', 'UNDER', 'AT_LEAST', 'YES', 'NO'
        )
    ),
    CHECK (line IS NULL OR line >= 0),
    UNIQUE (provider, provider_event_id, canonical_selection_key)
);

CREATE TABLE betting_market_selection_players (
    selection_id uuid NOT NULL REFERENCES betting_market_selections(id) ON DELETE CASCADE,
    participant_position smallint NOT NULL,
    player_id uuid REFERENCES players(id),
    provider_player_name text NOT NULL,
    participant_role text NOT NULL DEFAULT 'PRIMARY',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (participant_position >= 0),
    CHECK (participant_role IN ('PRIMARY', 'EITHER')),
    PRIMARY KEY (selection_id, participant_position),
    UNIQUE (selection_id, provider_player_name)
);

INSERT INTO betting_market_selections (
    fixture_id,
    provider,
    provider_event_id,
    fixture_provider_id,
    market_scope,
    market_type,
    period,
    outcome_type,
    line,
    canonical_selection_key,
    provider_market_label,
    provider_selection_label,
    raw_payload,
    created_at,
    updated_at
)
SELECT DISTINCT ON (provider, provider_event_id, market_key, selection_key)
    fixture_id,
    provider,
    provider_event_id,
    fixture_provider_id,
    'MATCH',
    CASE WHEN market_key = '1X2' THEN 'MATCH_RESULT_1X2' ELSE market_key END,
    'FULL_MATCH',
    selection_key,
    NULL,
    concat(
        CASE WHEN market_key = '1X2' THEN 'MATCH_RESULT_1X2' ELSE market_key END,
        '|FULL_MATCH|', selection_key, '|-|-'
    ),
    COALESCE(raw_payload ->> 'market', market_key),
    COALESCE(raw_payload ->> 'selection', selection_key),
    raw_payload,
    created_at,
    updated_at
FROM betting_market_observations
ORDER BY provider, provider_event_id, market_key, selection_key, observed_at DESC;

ALTER TABLE betting_market_observations
    ADD COLUMN selection_id uuid REFERENCES betting_market_selections(id);

UPDATE betting_market_observations AS observation
SET selection_id = selection.id
FROM betting_market_selections AS selection
WHERE selection.provider = observation.provider
  AND selection.provider_event_id = observation.provider_event_id
  AND selection.canonical_selection_key = concat(
      CASE
          WHEN observation.market_key = '1X2' THEN 'MATCH_RESULT_1X2'
          ELSE observation.market_key
      END,
      '|FULL_MATCH|', observation.selection_key, '|-|-'
  );

ALTER TABLE betting_market_observations
    ALTER COLUMN selection_id SET NOT NULL;

DROP INDEX betting_market_observations_fixture_observed_idx;
DROP INDEX betting_market_observations_provider_event_observed_idx;

DO $$
DECLARE
    constraint_name text;
BEGIN
    FOR constraint_name IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'betting_market_observations'::regclass
          AND contype = 'u'
    LOOP
        EXECUTE format(
            'ALTER TABLE betting_market_observations DROP CONSTRAINT %I',
            constraint_name
        );
    END LOOP;
END
$$;

ALTER TABLE betting_market_observations
    DROP COLUMN fixture_id,
    DROP COLUMN provider,
    DROP COLUMN provider_event_id,
    DROP COLUMN fixture_provider_id,
    DROP COLUMN market_key,
    DROP COLUMN selection_key,
    ADD CONSTRAINT betting_market_observations_selection_observed_key
        UNIQUE (selection_id, observed_at);

CREATE INDEX betting_market_selections_fixture_idx
    ON betting_market_selections(fixture_id)
    WHERE fixture_id IS NOT NULL;

CREATE INDEX betting_market_selections_provider_event_idx
    ON betting_market_selections(provider, provider_event_id);

CREATE INDEX betting_market_selections_type_idx
    ON betting_market_selections(market_scope, market_type, period);

CREATE INDEX betting_market_selection_players_player_idx
    ON betting_market_selection_players(player_id)
    WHERE player_id IS NOT NULL;

CREATE INDEX betting_market_observations_selection_observed_idx
    ON betting_market_observations(selection_id, observed_at DESC);
