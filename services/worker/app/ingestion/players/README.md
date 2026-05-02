# Worker Ingestion Players Module

## Purpose

Ingests Premier League player identity and squad data.

## Responsibilities

- Fetch Premier League squad/player identity from the configured provider.
- Store player names, clubs, positions, provider IDs, provider URLs, and raw provider rows.
- Maintain canonical `players.id` as the internal Stockball player ID.
- Support player-to-`PLAYER_SHARE` instrument creation during market seeding.

## Current Source

FBref is the current provider for Premier League player identity and squad data.

Default settings:

- Provider: `FBREF`
- FBref competition id: `9`
- Season: the season start year, for example `2025` for the 2025/26 season.

Environment:

- `STOCKBALL_WORKER_DATABASE_URL` or `DATABASE_URL`
- optional `STOCKBALL_FBREF_BASE_URL`, default `https://fbref.com`
- optional `STOCKBALL_FBREF_USER_AGENT`, should identify Stockball and a contact
- optional `STOCKBALL_FBREF_REQUEST_INTERVAL_SECONDS`, default `6.5`
- optional `STOCKBALL_FBREF_CACHE_TTL_SECONDS`, default `86400`

Command:

```bash
stockball-worker seed-players --league 9 --season 2025
```

The command reads FBref's Premier League player standard stats table, extracts player IDs from `/en/players/{id}/...` links, extracts team IDs from `/en/squads/{id}/...` links, and upserts canonical player rows by `(provider, provider_player_id)`.

## Sync Model

The player job is rerunnable and season-aware.

1. Fetch the FBref standard stats page for the configured competition and season.
2. Parse player rows from comment-wrapped or normal HTML tables.
3. Upsert `players` using provider `FBREF`.
4. Upsert `player_provider_refs` with FBref player URL and raw identity metadata.
5. Preserve the raw parsed row in `players.metadata.fbref_raw_row`.

Players leaving the Premier League are not deleted. Instrument lifecycle decisions stay outside ingestion.

## Boundaries

- Does not create trades.
- Does not mutate positions or balances.
- Does not decide bot behavior.
- Should preserve external provider IDs for later reconciliation.
