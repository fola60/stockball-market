# Worker Synthetic Traders Module

## Purpose

Owns synthetic trader strategy configuration and decision logic.

Synthetic traders are tagged accounts that behave like users but are controlled by the system. The API/accounts boundary provisions the account; this module configures strategy and decides trades after the account exists.

## Responsibilities

- Manage synthetic trader strategy configuration.
- Decide which bots should buy, sell, or hold.
- Apply strategy families such as social/hype-driven, stats-driven, market-watching, and noise traders.
- Respect bot position limits, cash limits, cooldowns, and execution settings.
- Send trade decisions to the trading engine through the worker client.

## Module Layout

- `models.py`: typed records for bot configs, bot state, portfolio context, candidate instruments, decisions, and tick outcomes.
- `config.py`: dataclass-based config parsing and validation for each supported engine.
- `repository.py`: worker-owned PostgreSQL reads for due bots, portfolios, positions, trades, price snapshots, market values, and stats.
- `service.py`: bot tick orchestration, universal risk filtering, idempotent request-id generation, and trading-engine submission.
- `spawner.py`: bulk bootstrap flow that asks the API to provision accounts and then attaches worker bot config rows.
- `engines/`: reusable strategy engine implementations.

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
- uses seeded fictional persona names by default, such as `maren_cross_42` / `Maren Cross`
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

Spawned bots share the selected base config row, but each bot receives its own `config_overrides` JSON. Randomization varies profile-personality values such as `signal_weights`, engine-specific scoring weights, sizing multipliers, and `execution.trade_probability`. It does not randomize hard safety rails such as max daily trades, max order count, max cash amount, or position exposure caps. Public persona names do not include strategy or profile labels; internal records still carry `account_type = SYNTHETIC_TRADER` and the worker bot config relationship.

Default engine profiles:

- `NOISE` -> `NOISE_RETAIL_BUYER`
- `MARKET_MOMENTUM` -> `MARKET_MOMENTUM_TRADER`
- `STATS_VALUE` -> `STATS_VALUE_CONSERVATIVE`
- `SOCIAL_SENTIMENT` -> `SOCIAL_HYPE_CHASER`
- `PORTFOLIO_REBALANCER` -> `PORTFOLIO_REBALANCER`

Required services:

- `STOCKBALL_WORKER_API_URL` or `STOCKBALL_API_URL` must point at the API service
- `STOCKBALL_WORKER_DATABASE_URL` must point at the shared Postgres database

## Tick Flow

1. Scheduler enqueues `SYNTHETIC_TRADER_TICK` jobs on a recurring minute window.
2. The job handler asks this module for due active bots.
3. The repository loads the bot account portfolio, positions, recent market history, and available stat context.
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
- The initial engine set is:
  - `NOISE`
  - `MARKET_MOMENTUM`
  - `STATS_VALUE`
  - `SOCIAL_SENTIMENT`
  - `PORTFOLIO_REBALANCER`
- Social/news signal tables are not implemented yet in this repo, so `SOCIAL_SENTIMENT` degrades to empty-signal holds instead of failing.

## Boundaries

- Does not execute trades directly.
- Does not provision account identities directly.
- Does not mutate prices, positions, or cash directly.
- Bot trades must go through the same trading-engine order endpoint as user trades.
- Bot accounts receive top-ups through the same top-up flow as normal users.
