# Worker Ingestion Fixtures Module

## Purpose

Ingests Premier League fixture and match-status data.

## Responsibilities

- Fetch upcoming fixtures.
- Store kickoff times, teams, and fixture IDs.
- Track lineup lock, match start, match end, and settlement status when available.
- Provide fixture facts used by freeze jobs.

## V1 Source

Use API-Football for fixture ingestion.

Default Premier League settings:

- API-Football league id: `39`
- Season: the season start year, for example `2025` for the 2025/26 season.
- Provider URL stored in fixtures: `https://v3.football.api-sports.io`

Required environment:

- `STOCKBALL_WORKER_DATABASE_URL` or `DATABASE_URL`
- `STOCKBALL_API_FOOTBALL_API_KEY`
- optional `STOCKBALL_API_FOOTBALL_API_BASE_URL`, default `https://v3.football.api-sports.io`
- optional `STOCKBALL_API_FOOTBALL_REQUEST_INTERVAL_SECONDS`, default `1.0`

Command:

```bash
stockball-worker ingest-fixtures --league 39 --season 2025 --from-date 2025-08-01 --to-date 2026-05-31
```

The command calls API-Football `/fixtures` with `league`, `season`, and optional date bounds, then upserts into `fixtures` by `(provider, provider_fixture_id)`.

## Boundaries

- Does not freeze instruments directly in the database.
- Fixture events should trigger worker jobs that call the trading engine freeze commands.
- Trading halt enforcement belongs to `trading-engine/freezes`.
