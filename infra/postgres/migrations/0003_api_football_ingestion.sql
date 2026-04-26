CREATE TABLE fixtures (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    provider_fixture_id text NOT NULL,
    league_provider_id text NOT NULL,
    season integer NOT NULL,
    kickoff_at timestamptz NOT NULL,
    home_team_provider_id text NOT NULL,
    home_team_name text NOT NULL,
    away_team_provider_id text NOT NULL,
    away_team_name text NOT NULL,
    status_short text,
    status_long text,
    elapsed integer,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_fixture_id)
);

CREATE INDEX fixtures_kickoff_at_idx
    ON fixtures(kickoff_at);

CREATE INDEX fixtures_league_season_kickoff_idx
    ON fixtures(league_provider_id, season, kickoff_at);

CREATE TABLE player_stat_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fixture_id uuid REFERENCES fixtures(id),
    player_id uuid REFERENCES players(id),
    provider text NOT NULL,
    provider_fixture_id text NOT NULL,
    provider_player_id text NOT NULL,
    team_provider_id text,
    team_name text,
    display_name text NOT NULL,
    rating numeric(6, 3),
    stats jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    observed_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_fixture_id, provider_player_id)
);

CREATE INDEX player_stat_observations_fixture_idx
    ON player_stat_observations(fixture_id);

CREATE INDEX player_stat_observations_player_idx
    ON player_stat_observations(player_id);

CREATE INDEX player_stat_observations_observed_at_idx
    ON player_stat_observations(observed_at DESC);
