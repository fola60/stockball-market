# Infrastructure

## Purpose

Contains local and deployment infrastructure configuration.

## Responsibilities

- Docker Compose configuration.
- PostgreSQL migration location.
- Redis configuration location.
- Future backup, health check, and deployment scripts.

## Boundaries

- Infrastructure config should not contain application business logic.
- Service-specific code belongs under `services`.
- Shared API contracts belong under `packages/contracts`.

## Local Docker

Copy `.env.example` to `.env` when local overrides or API keys are needed:

```bash
cp .env.example .env
```

Start the default local stack:

```bash
docker compose up --build
```

The default stack runs PostgreSQL, Redis, the trading engine, and the API. The worker
and scheduler are in the `worker` profile so scheduled jobs do not start automatically:

```bash
docker compose --profile worker up --build
```

Do not run player or market seeding before Docker Compose. The database and services
need to be running first. A normal local setup order is:

```bash
cp .env.example .env
docker compose up --build
```

Then, in another terminal, run the one-off data commands against the running stack.

Run one-off ingestion or seeding commands through the worker image, not from a
Dockerfile build step:

```bash
docker compose run --rm worker stockball-worker seed-players --league 9 --season 2025
docker compose run --rm worker stockball-worker ingest-fixtures --league 9 --season 2025
docker compose run --rm worker stockball-worker ingest-player-stats --league 9 --season 2025
docker compose run --rm worker stockball-worker import-market-values \
  --players-csv /data/market-values/players.csv \
  --valuations-csv /data/market-values/player_valuations.csv
docker compose run --rm worker stockball-worker seed-player-shares
```

FBref is the current player, fixture, and player-stat ingestion provider. It
uses FBref competition id `9` for the Premier League and does not require an
API key. Set `STOCKBALL_FBREF_USER_AGENT` in `.env` to a clear user agent with
a contact before running live FBref ingestion.

The host directory mounted at `/data/market-values` is controlled by
`MARKET_VALUES_DIR` in `.env`. The default points at the local downloaded archive under
`services/worker/app/ingestion/market_values/archive (1)`.

PostgreSQL migrations are mounted into `/docker-entrypoint-initdb.d` and run when the
database volume is first initialized. If you need to rerun migrations from scratch in
local development, remove the `postgres-data` volume first.
