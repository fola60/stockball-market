-- Canonical club names come from a different provider than FotMob ("Manchester Utd" vs
-- "Manchester United"), so the worker maps each club to the FotMob team most of its
-- linked players last appeared for. Stored so read paths do not re-aggregate ratings.
CREATE TABLE fotmob_club_teams (
    club text PRIMARY KEY,
    provider_team_id text NOT NULL,
    linked_players integer NOT NULL CHECK (linked_players > 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);
