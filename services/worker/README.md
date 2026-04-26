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

Seed current Premier League players from football-data.org:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_FOOTBALL_DATA_API_TOKEN=... \
stockball-worker seed-players --competition PL
```

This writes `https://api.football-data.org/v4` into `players.provider` and the football-data player ID into `players.provider_player_id`.

The football-data.org free plan is rate limited to 10 requests/minute for registered clients. The seed command defaults to one request every 7 seconds through `STOCKBALL_FOOTBALL_DATA_REQUEST_INTERVAL_SECONDS`, so a full Premier League seed stays under the free-tier limit.

Rate limit does not guarantee endpoint coverage. football-data.org's public pricing page currently lists `Squads` on `Free + Deep Data` and higher plans, so a plain free token may not be enough for this seed command.

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
