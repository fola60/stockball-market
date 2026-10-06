-- Separate from engine-consumed stat observations until the rating signal is enabled there.
CREATE TABLE fotmob_matches (
    match_id text PRIMARY KEY,
    league_id integer NOT NULL,
    season integer NOT NULL,
    kickoff_at timestamptz NOT NULL,
    home_team_id text NOT NULL,
    home_team_name text NOT NULL,
    away_team_id text NOT NULL,
    away_team_name text NOT NULL,
    finished boolean NOT NULL,
    first_finished_at timestamptz,
    source_url text NOT NULL,
    raw_fixture jsonb NOT NULL,
    ratings_fetched_at timestamptz,
    last_attempt_at timestamptz,
    last_error text,
    discovered_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX fotmob_matches_season_idx ON fotmob_matches(league_id, season, kickoff_at);

CREATE TABLE player_match_ratings (
    provider text NOT NULL DEFAULT 'FOTMOB' CHECK (provider = 'FOTMOB'),
    provider_match_id text NOT NULL REFERENCES fotmob_matches(match_id),
    provider_player_id text NOT NULL,
    player_id uuid REFERENCES players(id),
    display_name text NOT NULL,
    team_provider_id text NOT NULL,
    team_name text NOT NULL,
    rating numeric(5,3) CHECK (rating BETWEEN 0 AND 10),
    minutes_played integer CHECK (minutes_played BETWEEN 0 AND 150),
    source_url text NOT NULL,
    raw_payload jsonb NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, provider_match_id, provider_player_id)
);
CREATE INDEX player_match_ratings_player_idx ON player_match_ratings(player_id);
COMMENT ON COLUMN player_match_ratings.rating IS
    'FotMob final match rating on its native 0–10 scale. NULL means no published rating, not zero.';

CREATE VIEW player_season_ratings AS
SELECT r.provider, r.provider_player_id, r.player_id, m.league_id, m.season,
       count(*) AS appearances, count(r.rating) AS rated_appearances,
       avg(r.rating) AS average_rating, sum(r.minutes_played) AS minutes_played,
       max(m.kickoff_at) AS latest_match_at
FROM player_match_ratings r JOIN fotmob_matches m ON m.match_id = r.provider_match_id
GROUP BY r.provider, r.provider_player_id, r.player_id, m.league_id, m.season;
