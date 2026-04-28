# Worker Service

## Purpose

The worker service runs background and scheduled work.

It owns external data ingestion, synthetic trader decisions, recurring top-up scheduling, and other asynchronous jobs.

## Responsibilities

- Schedule and execute Redis-backed jobs.
- Ingest Premier League player, market-value, fixture, stats, social, and news data.
- Convert raw ingested data into signals for bot strategies.
- Decide synthetic trader actions.
- Send bot trade commands to the trading engine.
- Determine which accounts are due for top-ups.
- Send top-up credit commands to the trading engine.

## Must Not Own

- Trade execution.
- Direct price mutation.
- Direct position mutation.
- Direct cash mutation.
- Public API authentication.

## Internal Modules

- `scheduler`: schedules recurring jobs.
- `jobs`: job handlers executed by workers.
- `ingestion`: external data intake.
- `signals`: interpreted observations used by bot strategies.
- `synthetic_traders`: bot strategy and decision logic.
- `topups`: determines recurring credit eligibility.
- `clients`: internal service clients.

## One-Off Commands

Seed current Premier League players from API-Football:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_API_FOOTBALL_API_KEY=... \
stockball-worker seed-players --league 39 --season 2025
```

This writes `https://v3.football.api-sports.io` into `players.provider` and the API-Football player ID into `players.provider_player_id`. Fixtures and player stats use the same provider IDs, so stat observations can link directly to canonical players after this seed.

Ingest Premier League fixtures from API-Football:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_API_FOOTBALL_API_KEY=... \
stockball-worker ingest-fixtures --league 39 --season 2025
```

Ingest per-player stats for one API-Football fixture:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_API_FOOTBALL_API_KEY=... \
stockball-worker ingest-fixture-player-stats 1208040
```

Import Transfermarkt-derived market values from downloaded CSV files:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
stockball-worker import-market-values \
  --players-csv /path/to/players.csv \
  --valuations-csv /path/to/player_valuations.csv
```
