# Worker Service

## Purpose

The worker service runs background and scheduled work.

It owns external data ingestion, synthetic trader decisions, recurring top-up scheduling, and other asynchronous jobs.

The Compose topology runs two instances of the same worker image. `worker` consumes the
latency-sensitive trading queue (synthetic ticks and top-ups), while `ingestion-worker` consumes
external ingestion and document-processing jobs. The scheduler routes jobs between them. This
prevents a slow trading tick from starving social ingestion without duplicating scheduler runs.

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

- `entrypoints`: the `stockball-worker` command table, process wiring (scheduler and job
  worker), and service factories. `app/main.py` is only the console-script shim.
- `scheduler`: schedules recurring jobs.
- `jobs`: job handlers executed by workers.
- `ingestion`: external data intake.
- `synthetic_traders`: bot strategy and decision logic.
- `match_freezes`: decides which players are frozen for match day (lineup lock to
  post-match settlement) and asks the trading engine to open and release those freezes.
- `seeding`: one-off market seeding: pre-market valuations, fleet sizing, and initial share
  supply. It plans and audits; the trading engine applies prices, positions, and cash.
- `topups`: determines recurring credit eligibility.
- `clients`: internal service clients.

`scripts/probe_*.py` are manual checks against live providers; they are not part of the test
suite.

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
scripts/local-ingestion.sh fotmob --season 2025 --backfill
scripts/local-ingestion.sh fotmob --season 2026 --backfill
scripts/local-ingestion.sh shares
scripts/local-ingestion.sh twitter-sources --registry /path/to/reviewed-registry.json
scripts/local-ingestion.sh twitter-injuries
```

The helper creates `.venv-worker`, installs the worker package into it, and runs the matching `stockball-worker` command locally. FBref commands default to the season in progress (seasons roll over in July; 2026 is 2026-27); pin one with `--season` or `STOCKBALL_INGESTION_SEASON`.

`migrate` applies `infra/postgres/migrations/*.sql` to `STOCKBALL_WORKER_DATABASE_URL` for a fresh local Postgres database. The database must already exist. If the database already has Stockball tables without local migration metadata, it exits instead of reapplying non-idempotent migrations.

For local overrides:

```bash
cp scripts/local-ingestion.env.example .env.local-ingestion
```

`import-market-values` defaults to `$MARKET_VALUES_DIR/players.csv` and `$MARKET_VALUES_DIR/player_valuations.csv`.

`seed-player-shares` requires the trading engine to be running locally at `STOCKBALL_WORKER_TRADING_ENGINE_URL`.

`recalibrate-price-curves --multiplier M --depth-divisor D --reason TEXT` reshapes every
player-share price curve without moving any price (see
`services/trading-engine/src/price_impact/README.md`). It is a dry run unless `--apply` is
given; the default request id is one per UTC day and calibration, so a retry replays instead of
rebasing twice.

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

FotMob match ratings reach synthetic traders only when
`STOCKBALL_MATCH_RATING_SIGNALS_ENABLED=true` (migrations 0030–0032). They feed stats
confirmation and `STATS_VALUE` scoring, and drive the `EVENT_REACTION` profiles. See
`app/synthetic_traders/STRATEGY_ENGINES.md`.

### Direct Worker CLI

Seed current Premier League players from FBref:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_FBREF_USER_AGENT="StockballMarketWorker/0.1 (contact: ops@example.com)" \
stockball-worker seed-players --league 9
```

This writes `FBREF` into `players.provider`, stores the FBref player ID in `players.provider_player_id`, and records FBref URLs/raw rows in provider metadata and `player_provider_refs`.

Ingest Premier League fixtures from FBref:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_FBREF_USER_AGENT="StockballMarketWorker/0.1 (contact: ops@example.com)" \
stockball-worker ingest-fixtures --league 9
```

Ingest Premier League player stat tables from FBref:

```bash
STOCKBALL_WORKER_DATABASE_URL=postgres://... \
STOCKBALL_FBREF_USER_AGENT="StockballMarketWorker/0.1 (contact: ops@example.com)" \
stockball-worker ingest-player-stats --league 9 --stat-type standard --stat-type shooting
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
FBref players and stats are not fetched by the bootstrap process itself: they are queued as
`INGEST_PLAYERS` and `INGEST_PLAYER_STATS` runs on the ingestion worker, which must be running,
and the bootstrap waits for each to succeed (`--worker-ingestion-timeout-minutes`, default 30).
FBref's browser fallback is reliably challenged from one-off `docker compose run` containers but
not from the ingestion worker. The runs appear in the admin UI like any manual job.

Docker Compose uses the existing worker image rather than a separate image per job. The
`bootstrap` profile includes the ingestion worker, so this also starts it if needed:

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
The noise profiles increase participation for hourly undertraded instruments without changing
buy/sell direction. Candidate sampling includes discovery as well as held instruments. Fleet
projections remain capacity estimates: decision yield, available signals, and risk checks determine
actual fills. Trade probability is a single draw per tick, so adding candidates does not compound it.

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

### Seasons, League Roster, and Player Stats

Every season setting uses 0 to mean the season in progress, which rolls over each July, so the
daily jobs follow the league without a config change. `STOCKBALL_PLAYER_STATS_SCHEDULE_SEASON`
and the admin runtime setting pin a season only when set to a year.

Two daily jobs keep player data current:

- `daily-league-roster` (an hour before the stats import) refreshes the season's player list,
  lets the trading engine list newcomers, and halts trading for players no longer in the league
  with an `ADMIN_HALT` freeze keyed `not-in-league:<player id>`. A player who returns is released.
  A season list with fewer than 300 players or 18 clubs is treated as incomplete and halts no one.
- `daily-player-stats` imports FBref's season tables and freezes a dated copy of each player's
  totals in `player_season_stat_snapshots`.

`app.player_stats` turns those snapshots into per-90 profiles: totals are combined across stat
tables and clubs, early-season rates are blended with the player's previous season (or the
league median) worth eight full matches, and recent form is the per-90 output since the snapshot
three weeks earlier. Synthetic traders and seed pricing read the same profiles. FBref supplies no
match ratings and, since 2025, no chance-creation data, so those inputs are left out of scoring.

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
  --top-player-holder-percent 40 \
  --holder-price-exponent 1 \
  --target-seed-value-per-bot 250000 \
  --seed-value-jitter-percent 25 \
  --risk-limit-headroom-percent 75 \
  --dry-run

python3 -m app.main bootstrap-synthetic-portfolios \
  --all-active-synthetic-bots \
  --seed 20260903
```

Use repeated `--bot-id UUID` arguments instead of `--all-active-synthetic-bots` to target a
specific fleet. Omit `--seed` to generate one; the command always prints the resolved seed.
Social-sentiment bots are seeded like the rest of the fleet so contrarian profiles have positions
to sell into hype; social signals don't affect which players they are given.

Seed holdings follow value, as in a real market. The most valuable player is held by
`--top-player-holder-percent` of the bots (default 40%), and every other player by that share
scaled by (its price / the top price) ^ `--holder-price-exponent` (default 1, linear), never fewer
than `--min-holders-per-player`. Each bot's number of positions follows from those targets, with
diversified strategies holding more players than noise traders, and bots choose which players they
hold by strategy preference.

Every bot gets roughly `--target-seed-value-per-bot` (jittered by `--seed-value-jitter-percent`)
spread over its players, so no bot's net worth depends on which players it drew. Each position,
club and cash balance stays within `--risk-limit-headroom-percent` of the bot's own risk limits; a
bot seeded past its limits would spend every tick selling instead of trading. No bot holds more
than `--max-player-supply-per-bot` percent of a player, and the reserve keeps at least
`--reserve-supply-percent` of each player plus any supply the bots don't take. The dry run prints
the positions and seed-value spread per bot and the average holders per price quintile.

Bootstrap allocation is issuance, not trading. It transfers no cash and creates no orders,
trades, fees, price changes, or cash-ledger entries. It creates integer positions directly in
one audited transaction, values them at the instrument seed price, and assigns the configured
reserve to the dedicated `system-player-share-reserve` portfolio. A unique audit marker rejects
attempts to bootstrap an instrument twice. After issuance, every ownership and cash change must
use the normal trading-engine order path.

### Engine profile correctness

See [the strategy guide](app/synthetic_traders/STRATEGY_ENGINES.md#current-implementation-october-2026)
for current signal semantics, retired controls, and rollout ordering. Migration 0029 updates the
existing profiles. Deploy the trading engine first, then pause the worker while applying migrations
and deploying its update; resume it once its parser matches the migrated profiles.

Behavioral regression tests live in `tests/test_profile_regressions.py`. The end-to-end tests in
`tests/test_profile_postgres.py` require a disposable migrated PostgreSQL database and a running
trading engine connected to that same database. Set `STOCKBALL_PROFILE_TEST_DATABASE_URL` and
`STOCKBALL_PROFILE_TEST_ENGINE_URL` to run them; they insert test records and must not target a
shared or production database.

Final FotMob match ratings are stored separately in `player_match_ratings`, with season averages
in `player_season_ratings`. They are not yet consumed by the engine. See
[the ingestion guide](app/ingestion/fotmob/README.md) for scheduling, backfills and coverage queries.
