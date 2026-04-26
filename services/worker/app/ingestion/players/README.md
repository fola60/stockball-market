# Worker Ingestion Players Module

## Purpose

Ingests Premier League player identity and squad data.

## Responsibilities

- Fetch Premier League squads.
- Store player names, clubs, positions, nationality, age, and provider IDs.
- Maintain canonical player records.
- Support player-to-`PLAYER_SHARE` instrument creation during market seeding.

## V1 Source

Use API-Football as the V1 canonical player provider.

Why:

- It exposes Premier League players through league id `39` and season year.
- It is the same provider used for fixtures and per-fixture player stats.
- Using one provider for players, fixtures, and stats avoids cross-provider player ID matching in V1.
- It is structured JSON, which is safer than scraping HTML for the core player universe.

Fallback candidates:

- football-data.org: good for team and squad identity, but its player IDs differ from API-Football and squad endpoint access may require a paid tier.
- Sportmonks: broader commercial football API with teams, squads, player profiles, fixtures, and stats.
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

The current implementation seeds the `players` table from API-Football. It uses the API-Football base URL as the `players.provider` value, for example `https://v3.football.api-sports.io`, and stores the API-Football player ID in `players.provider_player_id`.

Required environment:

- `STOCKBALL_WORKER_DATABASE_URL` or `DATABASE_URL`
- `STOCKBALL_API_FOOTBALL_API_KEY`
- optional `STOCKBALL_API_FOOTBALL_API_BASE_URL`, default `https://v3.football.api-sports.io`
- optional `STOCKBALL_API_FOOTBALL_REQUEST_INTERVAL_SECONDS`, default `1.0`

Command:

```bash
stockball-worker seed-players --league 39 --season 2025
```

The command fetches `/players?league=39&season=2025`, follows API-Football pagination, and upserts each returned player into `players`. Nationality, date of birth, team ID, team name, age, height, weight, injury flag, photo URL, and the raw API-Football payload are stored in `players.metadata`.

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

Provider-specific fields and raw payloads should live in provider reference or observation tables. The current `players.provider` and `players.provider_player_id` columns are acceptable for V1 because players, fixtures, and player stats all use API-Football IDs. A future market-value provider will still require cross-provider references.

## Boundaries

- Does not create trades.
- Does not mutate positions or balances.
- Does not decide bot behavior.
- Should preserve external provider IDs for later reconciliation.
