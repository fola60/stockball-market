# Worker Ingestion Fixtures Module

## Purpose

Ingests Premier League fixture and match-status data.

## Responsibilities

- Fetch upcoming fixtures.
- Store kickoff times, teams, and fixture IDs.
- Track lineup lock, match start, match end, and settlement status when available.
- Provide fixture facts used by freeze jobs.

## V1 Source

Use FBref for fixture ingestion.

Default Premier League settings:

- FBref competition id: `9`
- Season: the season start year, for example `2025` for the 2025/26 season.
- Provider stored in fixtures: `FBREF`

Environment:

- `STOCKBALL_WORKER_DATABASE_URL` or `DATABASE_URL`
- optional `STOCKBALL_FBREF_BASE_URL`, default `https://fbref.com`
- optional `STOCKBALL_FBREF_USER_AGENT`, should identify Stockball and a contact
- optional `STOCKBALL_FBREF_REQUEST_INTERVAL_SECONDS`, default `6.5`
- optional `STOCKBALL_FBREF_CACHE_TTL_SECONDS`, default `86400`

Command:

```bash
stockball-worker ingest-fixtures --league 9 --season 2025 --from-date 2025-08-01 --to-date 2026-05-31
```

The command reads the FBref Premier League scores-and-fixtures table, preserves the raw parsed row, and upserts into `fixtures` by `(provider, provider_fixture_id)`. FBref match IDs are stored when a match-report URL is available; otherwise the provider fixture key is derived from competition, season, gameweek, and team provider IDs for rerunnable imports.

## Boundaries

- Does not freeze instruments directly in the database.
- Fixture events should trigger worker jobs that call the trading engine freeze commands.
- Trading halt enforcement belongs to `trading-engine/freezes`.
