# Stockball Build Order

## Build Strategy

Build the platform as thin vertical slices, not as isolated services that only work months later. Each milestone should leave the system runnable with one more market capability connected end to end.

The first slice should prove the most important boundary: users and bots request trades through the API or worker, but only the trading engine mutates prices, balances, positions, trades, and ledger entries.

## Milestone 1: Contracts And Database Foundation

Build first because every service depends on the same data model and command shapes.

Modules involved:

- `packages/contracts`
- `infra/postgres/migrations`
- `services/trading-engine/src/instruments`
- `services/trading-engine/src/portfolios`
- `services/trading-engine/src/positions`
- `services/trading-engine/src/ledger`

Deliverables:

- initial database schema for players, instruments, accounts, portfolios, positions, orders, trades, price snapshots, cash ledger entries, and idempotency keys
- shared OpenAPI contract for internal trading-engine commands
- Docker Compose with Postgres and Redis
- seed script or migration data for one test `PLAYER_SHARE` instrument and one test user portfolio

Definition of done:

- the database starts locally
- migrations apply from a clean database
- one seeded instrument and portfolio can be queried manually

## Milestone 2: Trading Engine Minimal Execution

Build the Rust trading engine before the public API because it owns the core market invariants.

Modules involved:

- `services/trading-engine/src/orders`
- `services/trading-engine/src/execution`
- `services/trading-engine/src/price_impact`
- `services/trading-engine/src/ledger`
- `services/trading-engine/src/portfolios`
- `services/trading-engine/src/positions`
- `services/trading-engine/src/instruments`
- `services/trading-engine/src/snapshots`
- `services/trading-engine/src/idempotency`

Deliverables:

- `POST /internal/v1/orders/execute`
- buy execution at the exact average price across the resulting curved price movement
- sell execution at the exact average price across the resulting curved price movement
- cash debit/credit through the ledger module
- position updates
- trade records
- price snapshots
- price curve driven by net shares purchased relative to shares outstanding
- configurable full-supply price multiplier, defaulting to `2.5`
- twelve-decimal internal price and cash precision, with display rounding left to clients
- idempotency key support for retry-safe commands

Definition of done:

- buying shares reduces cash, increases positions, records a trade, and increases instrument price
- selling shares increases cash, reduces positions, records a trade, and decreases instrument price
- duplicate requests with the same idempotency key do not execute twice

## Milestone 3: API Service Vertical Slice

Build the user-facing API after the trading engine can execute orders.

Modules involved:

- `services/api/app/accounts`
- `services/api/app/instruments`
- `services/api/app/portfolios`
- `services/api/app/orders`
- `services/api/app/clients`

Deliverables:

- basic account identity for test users
- `GET /v1/instruments`
- `GET /v1/instruments/:id`
- `GET /v1/instruments/:id/price-history`
- `GET /v1/portfolios/:id`
- `POST /v1/orders`
- API client that forwards order commands to the trading engine

Definition of done:

- a test user can place a buy or sell order through the API
- the API returns the trading-engine execution result
- updated instrument price, positions, cash, and price history can be read through the API

## Milestone 4: Worker Scheduling And Top-Ups

Build scheduled money movement before bots so synthetic traders and users can share the same credit rules.

Modules involved:

- `services/worker/app/scheduler`
- `services/worker/app/jobs`
- `services/worker/app/topups`
- `services/worker/app/clients`
- `services/trading-engine/src/ledger`
- `services/trading-engine/src/idempotency`

Deliverables:

- Redis-backed worker queue
- scheduled top-up job
- internal trading-engine command for ledger credits
- top-up records for auditability
- idempotent top-up request IDs

Definition of done:

- a scheduled job can credit eligible accounts
- top-up credits are applied by the trading engine, not directly by the worker
- rerunning the same top-up job does not double-credit an account

## Milestone 5: Synthetic Trader Accounts And First Strategy

Build bots once the normal order path and top-up path are working.

Modules involved:

- `services/api/app/accounts`
- `services/worker/app/synthetic_traders`
- `services/worker/app/jobs`
- `services/worker/app/clients`
- `services/trading-engine/src/orders`

Deliverables:

- synthetic trader account provisioning through the API/accounts boundary
- bot tagging by the API service so admin/internal tools can distinguish bots from real users
- strategy config storage
- one simple market-watching or noise strategy
- bot trade decisions sent through `POST /internal/v1/orders/execute`

Definition of done:

- the API can provision a tagged synthetic trader account
- the worker can attach strategy configuration to that bot account
- a bot can receive credits
- a bot can place a buy or sell order through the trading engine
- bot trades affect price exactly like user trades

## Milestone 6: Player And Market-Value Ingestion

Build ingestion after the trading path works with seeded data.

Modules involved:

- `services/worker/app/ingestion/players`
- `services/worker/app/ingestion/market_values`
- `services/trading-engine/src/instruments`

Deliverables:

- Premier League player import
- external market-value import
- canonical player/provider reference schema so player identity and market-value data can be reconciled across sources
- raw provider observation storage for squad and valuation imports
- player-to-instrument creation flow
- initial price seeding from market value
- fixed shares outstanding per player

Definition of done:

- the system can create tradable `PLAYER_SHARE` instruments from ingested data
- rerunning the Premier League squad sync updates clubs and league membership without duplicating players
- market values from a separate source can be matched to canonical players or queued for review
- every created instrument has an initial price, shares outstanding, and price impact unit

## Milestone 7: Market Freezes And Fixture Awareness

Build freeze logic before live-match or stats-driven bot behavior.

Modules involved:

- `services/worker/app/ingestion/fixtures`
- `services/worker/app/jobs`
- `services/trading-engine/src/freezes`
- `services/trading-engine/src/orders`

Deliverables:

- fixture ingestion
- lineup-lock or match-start detection
- internal freeze and unfreeze commands
- order rejection for frozen player-share instruments
- market status read API

Definition of done:

- affected player-share instruments can be frozen from a worker job
- orders for frozen instruments are rejected by the trading engine
- unaffected instruments remain tradable
- instruments can be unfrozen after settlement

## Milestone 8: Signals For Bot Decisions

Build stat and social signals only after bots can trade without them.

Modules involved:

- `services/worker/app/ingestion/social`
- `services/worker/app/ingestion/stats`
- `services/worker/app/ingestion/betting_markets`
- `services/worker/app/synthetic_traders/engines` (signal interpretation)

Deliverables:

- social mention volume observations
- basic positive/negative sentiment observations
- player stat observations
- pre-match and live betting market observations for bot context
- bot strategies that use signal observations

Definition of done:

- signals change bot buy/sell decisions
- signals do not directly mutate instrument prices
- prices still move only through executed trades
- betting market observations remain external context and do not set Stockball prices directly

## Milestone 9: Admin UI

Build admin views once enough backend behavior exists to inspect.

Modules involved:

- `apps/admin-ui`
- `services/api/app/admin`

Deliverables:

- instrument list and price history
- portfolio and position inspection
- bot account and trade activity views
- freeze status view
- ingestion/job status view

Definition of done:

- an admin can inspect why prices moved, which bots traded, and which instruments are frozen without querying the database manually

## Milestone 10: Hardening

Build after the first complete market loop works.

Modules involved:

- all services
- `infra`

Deliverables:

- structured logging
- health checks
- error handling and retries
- database backups
- minimal monitoring
- service-level tests and end-to-end tests

Definition of done:

- local Docker Compose can start the full system
- the core order flow has automated tests
- worker jobs are retry-safe
- database backup and restore has been tested once
