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

### Local Runner

Use the repo-level helper to run ingestion against local services without Docker:

```bash
scripts/local-ingestion.sh setup
scripts/local-ingestion.sh migrate
scripts/local-ingestion.sh players
scripts/local-ingestion.sh fixtures --from-date 2025-08-01 --to-date 2025-08-31
scripts/local-ingestion.sh stats --stat-type standard --stat-type shooting
scripts/local-ingestion.sh market-values
scripts/local-ingestion.sh shares
scripts/local-ingestion.sh twitter-sources --registry /path/to/reviewed-registry.json
scripts/local-ingestion.sh twitter-injuries
```

The helper creates `.venv-worker`, installs the worker package into it, and runs the matching `stockball-worker` command locally. FBref commands default to season `2025`; override with `--season` or `STOCKBALL_INGESTION_SEASON`.

`migrate` applies `infra/postgres/migrations/*.sql` to `STOCKBALL_WORKER_DATABASE_URL` for a fresh local Postgres database. The database must already exist. If the database already has Stockball tables without local migration metadata, it exits instead of reapplying non-idempotent migrations.

For local overrides:

```bash
cp scripts/local-ingestion.env.example .env.local-ingestion
```

`import-market-values` defaults to `$MARKET_VALUES_DIR/players.csv` and `$MARKET_VALUES_DIR/player_valuations.csv`.

`seed-player-shares` requires the trading engine to be running locally at `STOCKBALL_WORKER_TRADING_ENGINE_URL`.

Set `LOCAL_INGESTION_INSTALL_CHROMEDRIVER=1` in `.env.local-ingestion` if FBref browser fallback needs a local chromedriver install.

Twitter injury ingestion uses only the approved X API recent-search endpoint. It is disabled
until `STOCKBALL_TWITTER_POLICY_ACKNOWLEDGED=true`; recurring polling additionally requires
`STOCKBALL_TWITTER_INJURY_SCHEDULE_ENABLED=true`. Source accounts and player aliases must be
manually reviewed and synced before polling. See
`app/ingestion/social/twitter/README.md` for policy constraints, registry rules, cursor and
rate-limit behavior, classification, episode transitions, and availability output.

### Direct Worker CLI

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

Spawn a batch of synthetic trader accounts and attach them to a worker bot config:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_WORKER_API_URL=http://api:8000 \
stockball-worker spawn-synthetic-traders \
  --strategy-engine STATS_VALUE \
  --count 300 \
  --random-seed 20260613
```

Use `--config-key STATS_VALUE_AGGRESSIVE` instead of `--strategy-engine` when you want an exact seeded profile. Public names use fictional persona-style handles and display names by default; use `--name-style NUMBERED` with `--handle-prefix` and `--display-name-prefix` only for internal/test batches.

This command provisions accounts through the API and writes only the worker-owned `synthetic_trader_bots` attachment rows, including per-bot randomized `config_overrides`. Omit `--random-seed` for non-deterministic variation. It does not grant cash or write trades, positions, ledger entries, or prices.
