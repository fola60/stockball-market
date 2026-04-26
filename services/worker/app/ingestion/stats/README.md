# Worker Ingestion Stats Module

## Purpose

Future module for ingesting football performance and availability data.

## Responsibilities

- Fetch player stats from approved football data providers.
- Store appearances, minutes, goals, assists, cards, injuries, suspensions, and other relevant observations.
- Match provider player IDs to canonical Stockball players.
- Feed later `signals/stats` calculations.

## V1 Source

Use API-Football for per-fixture player statistics.

Required environment:

- `STOCKBALL_WORKER_DATABASE_URL` or `DATABASE_URL`
- `STOCKBALL_API_FOOTBALL_API_KEY`
- optional `STOCKBALL_API_FOOTBALL_API_BASE_URL`, default `https://v3.football.api-sports.io`
- optional `STOCKBALL_API_FOOTBALL_REQUEST_INTERVAL_SECONDS`, default `1.0`

Command:

```bash
stockball-worker ingest-fixture-player-stats 1208040
```

The command calls API-Football `/fixtures/players?fixture={fixture_id}` and upserts rows into `player_stat_observations` by `(provider, provider_fixture_id, provider_player_id)`.

Because V1 player seeding also uses API-Football, stat observations can resolve `player_id` by matching `(provider, provider_player_id)` against `players`. Observations remain nullable for defensive ingestion, but a properly seeded Premier League player universe should match most first-team fixture participants.

For the free tier, avoid live polling. A normal Premier League matchweek should be ingested after final whistle with roughly one stats request per fixture, plus fixture discovery requests.

## Boundaries

- Does not decide bot trades directly.
- Does not directly change prices.
- Stat interpretation belongs to `services/worker/app/signals/stats`.
