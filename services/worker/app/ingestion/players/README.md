# Worker Ingestion Players Module

## Purpose

Ingests Premier League player identity and squad data.

## Responsibilities

- Fetch Premier League squads.
- Store player names, clubs, positions, nationality, age, and provider IDs.
- Maintain canonical player records.
- Support player-to-`PLAYER_SHARE` instrument creation during market seeding.

## V1 Source

Primary candidate: `football-data.org`.

Why:

- It exposes Premier League data through competition code `PL`.
- Team resources include squad/person records with stable provider IDs.
- It is structured JSON, which is safer than scraping HTML for the core player universe.
- The same provider can later support fixtures and match-status ingestion if its plan coverage is sufficient.

Fallback candidates:

- Sportmonks: broader commercial football API with teams, squads, player profiles, fixtures, and stats.
- API-Football: broad coverage and low-friction access, but verify player ID stability and Premier League squad completeness before choosing it as canonical.
- Fantasy Premier League public data: useful as a development/bootstrap source for current Premier League player names and teams, but it should not become the canonical identity source unless we accept its unofficial/public endpoint risk and fantasy-specific fields.

## Sync Model

The player job should be rerunnable and season-aware.

1. Fetch current Premier League teams.
2. Fetch each team's squad.
3. Upsert provider references by `(provider, provider_player_id)`.
4. Upsert canonical player fields from the primary provider.
5. Mark `current_club`, `position`, `nationality`, `date_of_birth`, and Premier League membership as of the sync timestamp.
6. Mark previously seen Premier League players who are no longer returned as out-of-universe, not deleted.

Transfers and promotions/relegation should be represented as changed observations, not new Stockball players, when the provider ID or reconciliation rules identify the same person.

## Seed Command

The current implementation seeds the `players` table from football-data.org only. It uses the football-data API base URL as the `players.provider` value, for example `https://api.football-data.org/v4`, and stores the football-data player ID in `players.provider_player_id`.

Required environment:

- `STOCKBALL_WORKER_DATABASE_URL` or `DATABASE_URL`
- `STOCKBALL_FOOTBALL_DATA_API_TOKEN`
- optional `STOCKBALL_FOOTBALL_DATA_API_BASE_URL`, default `https://api.football-data.org/v4`
- optional `STOCKBALL_FOOTBALL_DATA_REQUEST_INTERVAL_SECONDS`, default `7.0`

Command:

```bash
stockball-worker seed-players --competition PL
```

The command fetches `/competitions/PL/teams`, then fetches `/teams/{teamId}` for each club and upserts each squad member into `players`. Nationality, date of birth, team ID, team name, and the raw football-data squad member payload are stored in `players.metadata`.

football-data.org's official API policy lists registered free-plan clients at 10 requests/minute. A full Premier League seed currently makes one competition-teams request plus one team-detail request per club, so roughly 21 calls. The default 7-second request interval keeps the worker below the free-plan limit and makes a full PL seed take about 2.5 minutes. If football-data.org still returns HTTP 429, the client honors `Retry-After` when present before retrying once.

Plan coverage is separate from rate limiting. The public football-data.org pricing page currently lists `Squads` on the `Free + Deep Data` tier and above, not on the plain free tier. If a free token cannot access `/teams/{teamId}` squad data, the seed command will need an upgraded football-data.org plan or a fallback source.

## Canonical Fields

Canonical player rows should eventually contain source-independent fields:

- display name
- normalized search name
- date of birth
- nationality
- current club
- current league or `is_current_premier_league`
- primary position
- active/inactive status

Provider-specific fields and raw payloads should live in provider reference or observation tables. The current `players.provider` and `players.provider_player_id` columns are acceptable for the seed-only schema, but they will not be enough once market values come from a second source.

## Boundaries

- Does not create trades.
- Does not mutate positions or balances.
- Does not decide bot behavior.
- Should preserve external provider IDs for later reconciliation.
