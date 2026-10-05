-- Daily snapshots of each player's season totals.
--
-- FBref publishes season-to-date tables (standard, shooting, passing, defense, keeper), and
-- `player_stat_observations` keeps only the latest copy of each. A snapshot freezes one
-- player's tables as they stood on a given day, so recent form is the difference between two
-- days' totals. One row per player, provider, season and day; a later ingest on the same day
-- refreshes that day's row. `tables` maps each stat table to the player's rows in it (one
-- per club, so a mid-season transfer keeps both clubs' totals).
CREATE TABLE player_season_stat_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id uuid NOT NULL REFERENCES players(id),
    provider text NOT NULL,
    season integer NOT NULL CHECK (season > 1900),
    snapshot_date date NOT NULL,
    teams text[] NOT NULL DEFAULT '{}',
    tables jsonb NOT NULL CHECK (jsonb_typeof(tables) = 'object'),
    captured_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (player_id, provider, season, snapshot_date)
);

CREATE INDEX player_season_stat_snapshots_latest_idx
    ON player_season_stat_snapshots (player_id, season, snapshot_date DESC);

-- Start the history from the tables already ingested.
WITH per_table AS (
    SELECT player_id, provider, season, stat_type,
           jsonb_agg(stats ORDER BY team_name NULLS LAST) AS rows,
           MAX(observed_at) AS observed_at
    FROM player_stat_observations
    WHERE player_id IS NOT NULL AND season IS NOT NULL AND stat_type IS NOT NULL
    GROUP BY player_id, provider, season, stat_type
),
teams AS (
    SELECT player_id, provider, season,
           array_agg(DISTINCT team_name) FILTER (WHERE team_name IS NOT NULL) AS teams
    FROM player_stat_observations
    WHERE player_id IS NOT NULL AND season IS NOT NULL
    GROUP BY player_id, provider, season
)
INSERT INTO player_season_stat_snapshots (player_id, provider, season, snapshot_date, teams, tables)
SELECT per_table.player_id, per_table.provider, per_table.season,
       MAX(per_table.observed_at)::date,
       COALESCE(teams.teams, '{}'),
       jsonb_object_agg(per_table.stat_type, per_table.rows)
FROM per_table
LEFT JOIN teams USING (player_id, provider, season)
GROUP BY per_table.player_id, per_table.provider, per_table.season, teams.teams
ON CONFLICT (player_id, provider, season, snapshot_date) DO NOTHING;
