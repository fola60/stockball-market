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

Seed current Premier League players from FBref:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_FBREF_USER_AGENT="StockballMarketWorker/0.1 (contact: ops@example.com)" \
stockball-worker seed-players --league 9 --season 2025
```

This writes `FBREF` into `players.provider`, stores the FBref player ID in `players.provider_player_id`, and records FBref URLs/raw rows in provider metadata and `player_provider_refs`.

Ingest Premier League fixtures from FBref:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_FBREF_USER_AGENT="StockballMarketWorker/0.1 (contact: ops@example.com)" \
stockball-worker ingest-fixtures --league 9 --season 2025
```

Ingest Premier League player stat tables from FBref:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_FBREF_USER_AGENT="StockballMarketWorker/0.1 (contact: ops@example.com)" \
stockball-worker ingest-player-stats --league 9 --season 2025 --stat-type standard --stat-type shooting
```

Import Transfermarkt-derived market values from downloaded CSV files:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
stockball-worker import-market-values \
  --players-csv /path/to/players.csv \
  --valuations-csv /path/to/player_valuations.csv
```
