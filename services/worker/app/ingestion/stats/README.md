# Worker Ingestion Stats Module

## Purpose

Ingests football performance observations from external providers.

## Responsibilities

- Fetch player stat tables from approved football data providers.
- Store normalized per-player observations with provider IDs, team, season, competition, source URL, and raw parsed rows.
- Match provider player IDs to canonical Stockball players.
- Feed the stats-value strategy engine.

## Current Source

Use FBref for Premier League player stat tables.

Default stat types:

- `standard`
- `shooting`
- `passing`
- `defense`
- `keeper`

Environment:

- `STOCKBALL_WORKER_DATABASE_URL` or `DATABASE_URL`
- optional `STOCKBALL_FBREF_BASE_URL`, default `https://fbref.com`
- optional `STOCKBALL_FBREF_USER_AGENT`, should identify Stockball and a contact
- optional `STOCKBALL_FBREF_REQUEST_INTERVAL_SECONDS`, default `6.5`
- optional `STOCKBALL_FBREF_CACHE_TTL_SECONDS`, default `86400`

Command:

```bash
stockball-worker ingest-player-stats --league 9 --season 2025 --stat-type standard --stat-type shooting
```

If `--stat-type` is omitted, the default stat types are ingested. Each row is upserted into `player_stat_observations` using provider `FBREF`; raw parsed rows stay in `raw_payload`.

## Boundaries

- Does not decide bot trades directly.
- Does not directly change prices.
- Stat interpretation belongs to the synthetic trader strategy engines in `services/worker/app/synthetic_traders/engines`.
