# Worker Synthetic Traders Module

## Purpose

Owns synthetic trader strategy configuration and decision logic.

Synthetic traders are tagged accounts that behave like users but are controlled by the system. The API/accounts boundary provisions the account; this module configures strategy and decides trades after the account exists.

## Responsibilities

- Manage synthetic trader strategy configuration.
- Decide which bots should buy, sell, or hold.
- Apply strategy families such as social, stats, betting-market, market-momentum, and noise traders.
- Respect bot position limits, cash limits, cooldowns, and execution settings.
- Send trade decisions to the trading engine through the worker client.

## Module Layout

- `models.py`: typed records for bot configs, bot state, portfolio context, candidate instruments, decisions, and tick outcomes.
- `config.py`: dataclass-based config parsing and validation for each supported engine.
- `repository.py`: worker-owned PostgreSQL reads for due bots, portfolios, positions, trades, price snapshots, market values, stats, player-linked betting odds, and (when `STOCKBALL_MATCH_RATING_SIGNALS_ENABLED`) FotMob rating profiles, recent rated matches and their closing odds.
- `service.py`: bot tick orchestration, universal risk filtering, idempotent request-id generation, and trading-engine submission.
- `spawner.py`: bulk bootstrap flow that asks the API to provision accounts and then attaches worker bot config rows.
- `engines/`: reusable strategy engine implementations.

One-off share issuance and development-market bootstrap orchestration live in `app/seeding`
(`portfolios.py` and `dev_market.py`).

## Spawning Bots

Use the worker CLI for bootstrap batches:

```bash
stockball-worker spawn-synthetic-traders \
  --config-key NOISE_RETAIL_BUYER \
  --count 25 \
  --handle-prefix noise-buyer \
  --display-name-prefix "Noise Buyer" \
  --name-style NUMBERED
```

You can also select an engine family and let the worker choose its default seeded profile:

```bash
stockball-worker spawn-synthetic-traders \
  --strategy-engine STATS_VALUE \
  --count 10 \
  --random-seed 20260613
```

The command:

- calls the API internal account endpoint to create each `SYNTHETIC_TRADER` account and portfolio
- inserts one `synthetic_trader_bots` row per account using the selected `synthetic_trader_bot_configs.config_key`
- stores per-bot randomized `config_overrides` for profile-specific scoring, sizing, and execution variation
- uses seeded persona names from culturally coherent name pools by default, with weighted user-like handle forms such as `maeve.kerr`, `maeve_kerr92`, `maeve-kerr`, or `maevek`
- checks every existing account handle before generating a batch, preventing synthetic names from colliding with existing users or bots
- leaves cash funding to the existing top-up or ledger command paths

Useful options:

- `--config-key`: exact seeded profile to attach, e.g. `SOCIAL_CONTRARIAN`
- `--strategy-engine`: engine family to spawn using the worker default profile
- `--name-style`: public naming mode, default `PERSONA`; use `NUMBERED` for deterministic prefixed handles
- `--handle-prefix`: required with `--name-style NUMBERED`
- `--display-name-prefix`: required with `--name-style NUMBERED`
- `--start-index`: first numeric suffix, default `1`
- `--random-seed`: optional deterministic seed for reproducing per-bot config randomization
- `--status`: initial bot status, default `ACTIVE`

Spawned bots share the selected base config row, but each bot receives its own `config_overrides` JSON. Randomization varies profile-personality values such as `signal_weights`, engine-specific scoring weights, sizing multipliers, and `execution.trade_probability`. It does not randomize hard safety rails such as max daily trades, max order count, max cash amount, or position exposure caps. Public persona names do not include strategy or profile labels; internal records still carry `account_type = SYNTHETIC_TRADER` and the worker bot config relationship. Persona handles probabilistically use dots, underscores, dashes, joined names, initials, reversed names, and occasional two-digit, year-like, or four-digit suffixes. The bundled corpus keeps seeded runs reproducible and avoids a runtime dependency on a third-party identity API.

Default engine profiles:

- `NOISE` -> `NOISE_RETAIL_BUYER`
- `MARKET_MOMENTUM` -> `MARKET_MOMENTUM_TRADER`
- `STATS_VALUE` -> `STATS_VALUE_CONSERVATIVE`
- `SOCIAL_SENTIMENT` -> `SOCIAL_HYPE_CHASER`
- `PORTFOLIO_REBALANCER` -> `PORTFOLIO_REBALANCER`
- `BETTING_MARKET_VALUE` -> `BETTING_MARKET_CONSERVATIVE`

Required services:

- `STOCKBALL_WORKER_API_URL` or `STOCKBALL_API_URL` must point at the API service
- `STOCKBALL_WORKER_DATABASE_URL` must point at the shared Postgres database

## Tick Flow

1. Scheduler enqueues `SYNTHETIC_TRADER_TICK` jobs on a recurring minute window.
2. The job handler asks this module for due active bots.
3. The repository loads the bot account portfolio, positions, recent market history, and available stat context. Market price and trade history is hydrated into a process-local rolling 30-day cache on first use; later batches query only a small overlapping delta and deduplicate rows by ID.
4. The assigned engine produces raw buy, sell, or hold decisions.
5. The service applies universal execution rules before any order is submitted:
   - available cash
   - sell quantity availability
   - min and max trade cash limits
   - max trade cash percentage
   - max player position percentage
   - max team exposure percentage where club data exists
   - min cash reserve
   - max daily trades
   - cooldown
   - trade probability
   - size noise
   - max orders per tick
6. Valid orders are sent through `app.clients.trading_engine`.
7. The worker updates `last_ticked_at` and `next_tick_after` even when the bot holds.

## Design Notes

- [Strategy engines](./STRATEGY_ENGINES.md) define reusable bot decision formulas and profile configuration ideas.
- `synthetic_trader_bot_configs` stores reusable strategy-engine profile configs.
- `synthetic_trader_bots` maps one tagged synthetic trader account from `accounts` to one config, with optional per-bot JSON overrides.
- Default reusable configs are seeded by [0007_synthetic_trader_config_seeds.sql](/Users/afolabiadekanle/repos/stockball-market/infra/postgres/migrations/0007_synthetic_trader_config_seeds.sql).
- Betting profiles are seeded by [0011_betting_market_trader_profiles.sql](/Users/afolabiadekanle/repos/stockball-market/infra/postgres/migrations/0011_betting_market_trader_profiles.sql).
- The implemented engine set is:
  - `NOISE`
  - `MARKET_MOMENTUM`
  - `STATS_VALUE`
  - `SOCIAL_SENTIMENT`
  - `PORTFOLIO_REBALANCER`
  - `BETTING_MARKET_VALUE`
- `SOCIAL_SENTIMENT` reads current social-signal snapshots when social signals are enabled; absent or stale signals safely produce holds.
- `BETTING_MARKET_VALUE` reads player-linked goalscorer, assist, score-or-assist, shots, and shots-on-target probabilities. Missing, stale, or insufficiently broad odds produce holds.

To spawn betting bots, select the default conservative profile by engine or choose the
aggressive profile explicitly:

```bash
stockball-worker spawn-synthetic-traders --strategy-engine BETTING_MARKET_VALUE --count 50
stockball-worker spawn-synthetic-traders --config-key BETTING_MARKET_AGGRESSIVE --count 50
```

## Boundaries

- Does not execute trades directly.
- Does not provision account identities directly.
- Does not mutate prices or cash directly.
- The audited `bootstrap-synthetic-portfolios` issuance command is the sole narrow exception for
  direct initial position creation; it rejects prior ownership and never creates market activity.
- The development bootstrap has one additional audited pre-market exception: it can adjust an
  instrument only before any position, order, or trade exists, records the adjustment in both the
  valuation audit and price history, and cannot apply twice.
- Bot trades must go through the same trading-engine order endpoint as user trades.
- Bot accounts receive top-ups through the same top-up flow as normal users.
- Social-sentiment profiles and social inputs are excluded from bootstrap allocation for now.
