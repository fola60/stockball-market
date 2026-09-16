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

The provider-neutral social pipeline discovers approved subscriptions from PostgreSQL and needs
no paid provider credentials for Bluesky or RSS. Derived social snapshots reach synthetic traders
only when `STOCKBALL_SOCIAL_SIGNALS_ENABLED=true`; snapshots older than
`STOCKBALL_SOCIAL_SIGNAL_MAX_AGE_SECONDS` (default `3600`) are ignored. See
`app/ingestion/social/OPERATIONS.md` for source approval and replay procedures.

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

### Complete Development Market Bootstrap

Use the declarative bootstrap when you want instruments, a funded and diversified bot fleet,
and initial player-share ownership from a single command. It is a read-only preview unless
`--commit` is present:

```bash
cd services/worker
python3 -m scripts.bootstrap_dev_market \
  --target-trades-per-hour-per-instrument 2 \
  --max-bots unlimited \
  --random-seed 20260915

python3 -m scripts.bootstrap_dev_market \
  --target-trades-per-hour-per-instrument 2 \
  --max-bots 5000 \
  --random-seed 20260915 \
  --commit
```

To refresh players, stats, approved social feeds, and Transfermarkt CSV data first, add
`--ingest-data`, `--season`, and `--market-values-dir /path/to/csv-directory` to the committed
command. The worker aggregates a seven-day social signal after polling (configurable with
`--social-lookback-hours`). External ingestion is never attempted by a dry-run.

Docker Compose uses the existing worker image rather than a separate image per job:

```bash
STOCKBALL_BOOTSTRAP_TARGET_TRADES_PER_HOUR=2 \
docker compose --profile bootstrap run --rm bootstrap-dev-market
```

The fleet planner estimates successful hourly trades from effective tick cadence, decision yield,
trade probability, cooldown, per-tick order limits, and daily trade caps. It keeps all ten seeded
profiles represented, increases candidate coverage to the complete instrument universe, and adds
25% capacity by default for popularity-weighted activity above the per-instrument floor. Existing
active bots are reused and receive the same activity overrides; only profile deficits are spawned.
Use `--popularity-headroom` to change the extra capacity. The default `--max-bots 5000` is a
safety limit; pass `--max-bots unlimited` (or `none`) to remove it.
The noise profiles additionally rank hourly undertraded instruments and bias their next eligible
orders toward that gap, while signal-led profiles continue concentrating extra volume on popular
players.

Pre-market player prices use a market-value anchor adjusted by percentile signals. Defaults are
45% latest market value, 45% player stats, and 10% social sentiment. Missing signals are neutral,
prices are clamped to `£1–£250`, and only instruments with no positions, orders, or trades can be
adjusted. Every adjustment is stored in `dev_market_bootstrap_instrument_valuations` and a price
snapshot. Applied valuations, top-ups, bot counts, and portfolio issuance are idempotent on reruns.
The report distinguishes projected activity from observed trades; the recurring synthetic-trader
job must be running for the projection to become market activity.
The recurring job processes up to 500 due bots each minute, providing 30,000 scheduled bot ticks
per hour of runtime capacity; the bootstrap report's projected tick demand should remain below
that ceiling for this single-worker development topology.

### Synthetic Portfolio Bootstrap

Run the market bootstrap in this order:

1. Spawn the synthetic trader fleet.
2. Seed players, market values, and player-share instruments.
3. Fund synthetic accounts through the existing trading-engine top-up/admin path.
4. Preview and commit the one-off portfolio issuance.

```bash
cd services/worker
python3 -m app.main bootstrap-synthetic-portfolios \
  --all-active-synthetic-bots \
  --seed 20260903 \
  --min-holders-per-player 5 \
  --max-player-supply-per-bot 20 \
  --reserve-supply-percent 10 \
  --max-positions-per-bot 100 \
  --dry-run

python3 -m app.main bootstrap-synthetic-portfolios \
  --all-active-synthetic-bots \
  --seed 20260903
```

Use repeated `--bot-id UUID` arguments instead of `--all-active-synthetic-bots` to target a
specific fleet. Omit `--seed` to generate one; the command always prints the resolved seed.
Social-sentiment bots and social signals are intentionally excluded from this bootstrap.

Bootstrap allocation is issuance, not trading. It transfers no cash and creates no orders,
trades, fees, price changes, or cash-ledger entries. It creates integer positions directly in
one audited transaction, values them at the instrument seed price, and assigns the configured
reserve to the dedicated `system-player-share-reserve` portfolio. A unique audit marker rejects
attempts to bootstrap an instrument twice. After issuance, every ownership and cash change must
use the normal trading-engine order path.
