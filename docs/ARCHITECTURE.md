# Stockball Architecture

## Architecture Style

Stockball will use a lightweight multi-language service architecture.

The goal is to get the benefits of separating concerns without taking on expensive infrastructure too early. Services should be split only where the boundary is valuable.

V1 services:

- `api-service`: public and admin API
- `trading-engine`: trade execution and price mutation
- `worker-service`: ingestion, scheduled jobs, and synthetic trader decisions
- `admin-ui`: internal dashboard
- `postgres`: durable database
- `redis`: lightweight job queue and cache

Communication defaults:

- REST over HTTP for direct service commands
- Redis-backed jobs for scheduled/background work
- PostgreSQL for durable state
- no Kafka, Kubernetes, or gRPC for V1

## High-Level Flow

```text
Admin UI / Client
      |
      v
API Service
      |
      | REST command
      v
Trading Engine
      |
      v
PostgreSQL

Worker Service
      |
      | REST command
      v
Trading Engine

Worker Service
      |
      | scheduled jobs
      v
Redis
```

## Service Boundaries

### API Service

Recommended language: Python with FastAPI.

Purpose:

- expose the public API
- expose admin API endpoints
- authenticate users and admins
- read market data for clients
- receive user order requests
- forward trade execution commands to the trading engine

The API service should not execute trades directly. It can validate request shape and user identity, but final trading validation belongs to the trading engine.

Internal modules:

- `accounts`: real user accounts, authentication, admin roles
- `assets`: read APIs for player assets and current market data
- `portfolios`: read APIs for user cash, holdings, and PnL
- `orders`: public order endpoint and request validation
- `admin`: admin-only views for market state, bots, freezes, and ingestion status
- `clients.trading_engine`: HTTP client for internal trading-engine commands

Allowed writes:

- user/account records
- sessions/auth records
- admin audit records

Avoid writes:

- trades
- holdings
- asset prices
- price snapshots
- trade-related cash mutations

### Trading Engine

Recommended language: Rust.

Purpose:

- execute buy and sell orders
- enforce trading freezes
- check cash and share availability
- mutate portfolio cash and holdings
- create orders and trades
- apply the price-impact rule
- create price snapshots
- expose internal trading commands

This is the consistency-critical service. Any action that changes prices, holdings, balances, or trades must go through the trading engine.

Internal modules:

- `orders`: validates order commands and creates order records
- `execution`: fills orders against the platform quote
- `price_impact`: applies the V1 linear price movement rule
- `ledger`: records all cash balance changes, including trade debits/credits and scheduled top-ups
- `portfolios`: mutates cash balances and holdings
- `assets`: reads and updates current player-asset price/status
- `freezes`: enforces market-freeze rules
- `snapshots`: records historical price changes
- `idempotency`: prevents duplicate order or top-up execution from retries


Allowed writes:

- orders
- trades
- holdings
- portfolio cash balances caused by trades
- portfolio cash balances caused by scheduled top-ups
- cash ledger entries
- player-asset current prices
- price snapshots
- market-freeze state

Avoid writes:

- user authentication
- raw ingestion data
- social/stat observations
- bot strategy configuration

### Worker Service

Recommended language: Python.

Purpose:

- run scheduled jobs
- ingest Premier League player data
- ingest market values
- ingest fixture and lineup data
- ingest social/stat signals
- make synthetic trader decisions
- apply recurring credit top-ups
- send bot trade commands to the trading engine

The worker service may decide that a bot wants to buy or sell. It must not directly mutate prices, holdings, or balances. Bot trades go through the same trading-engine endpoint as user trades.

Internal modules:

- `scheduler`: creates recurring jobs
- `jobs`: job handlers pulled from Redis
- `ingestion.players`: Premier League squads and player identity
- `ingestion.market_values`: external market-value data
- `ingestion.fixtures`: fixtures, lineups, and match status
- `signals.social`: mention volume and sentiment observations
- `signals.stats`: player performance observations
- `synthetic_traders`: bot accounts, strategy selection, and trade decisions
- `topups`: recurring virtual-cash allocations
- `clients.trading_engine`: HTTP client for bot trades, top-up credits, and freeze commands

Allowed writes:

- players and player metadata
- raw provider records
- fixtures and fixture status
- social/stat signal observations
- synthetic trader strategy configuration
- ingestion run logs
- top-up records

Avoid writes:

- trades
- holdings
- asset prices
- price snapshots
- trade-related cash mutations

### Admin UI

Recommended language: TypeScript with a simple React or Next.js app.

Purpose:

- inspect market state
- view players and assets
- view synthetic trader activity
- view order/trade history
- inspect price changes
- inspect frozen players
- inspect ingestion and job failures

The admin UI should only talk to the API service. It should not call the trading engine or database directly.

## Infrastructure Modules

### PostgreSQL

PostgreSQL is the source of truth.

Stores:

- users and accounts
- players
- player assets
- portfolios
- holdings
- orders
- trades
- price snapshots
- market freezes
- fixtures
- signal observations
- synthetic trader configuration
- job/ingestion audit records

The database may be shared in V1 for cost reasons, but table ownership must still be respected at the service layer.

### Redis

Redis is infrastructure, not business logic.

Used for:

- scheduled job queues
- background jobs
- retry queues
- short-lived locks
- lightweight cache where useful

Redis should not be treated as durable source-of-truth storage. Anything important must end up in PostgreSQL.

## Communication Contracts

### Direct Commands

Use REST for commands where the caller needs an immediate result.

Examples:

- API service calls trading engine to execute a user order
- worker service calls trading engine to execute a bot order
- worker service calls trading engine to freeze or unfreeze assets

Example endpoint:

```http
POST /internal/v1/orders/execute
```

Example payload:

```json
{
  "request_id": "req_123",
  "account_id": "account_123",
  "asset_id": "asset_456",
  "side": "BUY",
  "shares": 10
}
```

### Background Jobs

Use Redis-backed jobs when work can happen asynchronously.

Examples:

- ingest players
- ingest social signals
- ingest fixtures
- run synthetic trader tick
- apply recurring top-ups
- check match freeze transitions

Redis stores the job. The worker service executes the job.

### Shared Contracts

Keep request and response schemas in a shared contracts folder.

Recommended repo location:

```text
packages/contracts/
```

Start with OpenAPI/JSON schema contracts. Move to protobuf/gRPC later only if the REST contracts become hard to maintain or performance-sensitive.

## Core Module Ownership Rules

- Only the trading engine executes trades.
- Only the trading engine changes player-asset prices.
- Only the trading engine mutates holdings after buy/sell activity.
- Worker service can decide bot behavior, but cannot directly execute bot trades.
- API service can authenticate users and accept order requests, but cannot fill orders.
- Admin UI reads through the API service only.
- Redis queues work but never owns business decisions.
- PostgreSQL stores durable state, but services must still respect table ownership.

## V1 Price Ownership

The V1 price rule is intentionally simple:

- buy orders increase price by `shares_bought * price_impact_unit`
- sell orders decrease price by `shares_sold * price_impact_unit`

This rule belongs inside the trading engine.
This will be subject to change after fleshing out core modules

Stats, sentiment, and market-watching signals do not directly change prices in V1. They only influence synthetic trader decisions. Synthetic traders then affect prices by buying or selling through the trading engine.

## Suggested Repository Layout

```text
stockball-market/
  services/
    api/
    trading-engine/
    worker/
    admin-ui/

  packages/
    contracts/

  infra/
    docker-compose.yml
    postgres/
      migrations/

  docs/
    ARCHITECTURE.md
```

## First Build Slice

Build the smallest end-to-end vertical slice first:

- seed one player and one player asset
- create one user portfolio
- expose `POST /v1/orders` from the API service
- forward the order to the trading engine
- execute the trade in the trading engine
- update cash, holdings, asset price, trade record, and price snapshot
- read the updated asset and portfolio through the API service

This validates the service boundaries before adding ingestion, synthetic traders, or admin views.
