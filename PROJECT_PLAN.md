# Stockball Market Project Plan

## Summary

Build a backend-first, virtual-cash football market focused exclusively on the Premier League, with an internal admin console and APIs rather than a consumer-grade app. The core product is a simulated exchange where users buy and sell player-share instruments, prices move only from buying and selling activity, and synthetic traders create believable liquidity before real user demand exists.

V1 will not include team or national-team index funds. Those remain part of the longer-term vision, but `PLAYER_SHARE` instruments are the only tradable instruments in the first release.

The architecture uses `Instrument` as the core tradable concept for extensibility. Derivatives such as options, futures, match contracts, margin, shorting, expiry, exercise, and settlement are explicitly out of scope for V1.

Architecture and service/module boundaries are defined in `docs/ARCHITECTURE.md`.

## Core V1 Product Decisions

- Instrument universe: Premier League player shares only.
- Portfolio currency: virtual cash only.
- Product shape: backend-first APIs plus an internal admin console.
- Market participants: real users plus synthetic traders that appear as tagged user accounts.
- Team and national-team funds: out of scope for V1.
- Live matches: trading freezes for affected players during matches.
- User positions: long-only.

## Synthetic Trader Model

Synthetic traders are first-class market participants that behave like user accounts, but carry a tag so they can be identified internally.

Each synthetic trader should have:

- an account and portfolio
- the same starting balance rules as normal users
- recurring credit top-ups on a weekly or monthly cadence
- configurable position limits
- strategy parameters
- trading history and positions like any other participant

Bot strategy families in V1:

- social/hype-driven traders reacting to positive or negative attention
- stats-driven traders reacting to football performance signals
- market-watching traders reacting to price movement and order flow
- noise traders creating background activity

Synthetic traders will decide whether to buy or sell based on multiple factors, but price formation itself will remain simple: prices move only because shares are bought or sold.

Future strategy inputs may include pre-match betting market observations such as bookmaker or exchange odds and implied probabilities. These should be treated as external context for bots and admin analysis, not as direct Stockball price inputs unless a later pricing milestone explicitly changes the price-formation rules.

## Price Formation Spec

### Initial Seeding

- Scrape or ingest the Premier League player universe and a market-value field for each player.
- Use the external market value as the initial valuation anchor for each player.
- Convert that market value into an initial share price using a fixed scaling rule.
- Assign a fixed number of shares outstanding per player for V1.

Suggested starting approach:

- `initial_price = market_value / scaling_factor`
- `shares_outstanding = fixed_constant_per_player`

This keeps setup simple while preserving relative differences between players.

### Price Movement Rule

For V1, share prices are affected solely by trading activity.

Use a simple linear price-impact rule:

- every buy increases the price by `shares_bought * price_impact_unit`
- every sell decreases the price by `shares_sold * price_impact_unit`

Example:

- if `price_impact_unit = 0.02`
- buying 10 shares increases price by `0.20`
- selling 10 shares decreases price by `0.20`

This means:

- football stats and sentiment do not directly change price in V1
- stats and sentiment only influence synthetic trader decisions
- synthetic traders create price movement indirectly through their trades

### Execution Model

V1 should use a platform-quoted market instead of a true matching engine.

- users place buy and sell orders against the platform
- the platform fills orders at the current quoted price
- after execution, the instrument price is updated using the share-impact rule

This avoids the complexity of maintaining an order book and matching user orders against each other.

### Trading Freeze Rules

- freeze trading for affected players during live matches
- freeze begins at lineup lock
- freeze ends after post-match settlement
- reject or pause any new orders for frozen players

## Build Order

### 1. Market schema and rules

Define the core entities and lock the market rules before building ingestion or trading flows.

Key entities:

- `Player`
- `Instrument`
- `Portfolio`
- `Position`
- `Order`
- `Trade`
- `PriceSnapshot`
- `SyntheticTrader`
- `MarketFreeze`

### 2. Player ingestion and seeding

- ingest Premier League squads and player metadata
- ingest a market-value field for each player
- maintain canonical Stockball player IDs separately from external provider IDs
- store cross-provider player references so squad data and valuation data can come from different sources
- create canonical player and `PLAYER_SHARE` instrument records
- seed initial prices and shares outstanding

### 3. Trading engine

- implement buy and sell flows
- update balances and positions
- record trades and price snapshots
- apply the simple share-based price-impact rule after each trade

### 4. Synthetic trader engine

- provision tagged bot accounts through the API/accounts boundary
- configure synthetic trader strategies in the worker service
- allocate starting balances
- support recurring top-ups
- implement strategy modules for social, stats, market-watching, and noise behavior
- execute bot trades through the same trading path as users

### 5. Market operations

- implement fixture-aware trading freezes
- add scheduled jobs for bot activity and account top-ups
- add admin visibility into traders, portfolios, trades, and price movements

### 6. API and admin console

- expose instrument, trade, portfolio, and market-status APIs
- expose admin views for bot activity, freezes, and price history

## Initial API Surface

- `GET /v1/instruments`
- `GET /v1/instruments/:id`
- `GET /v1/instruments/:id/price-history`
- `GET /v1/fixtures`
- `GET /v1/market-status`
- `POST /v1/orders`
- `GET /v1/portfolios/:id`
- `GET /v1/admin/synthetic-traders`
- `GET /v1/admin/market-freezes`

## Test Scenarios

- buying shares increases price by the configured per-share amount
- selling shares decreases price by the configured per-share amount
- consecutive buys and sells update positions, cash, and price history correctly
- frozen players reject new orders during matches
- synthetic traders can place trades through the same path as users
- synthetic traders receive recurring credit allocations on schedule
- social/stat/market signals change bot behavior without directly mutating prices

## Assumptions And Defaults

- V1 is a simulation only, with no real-money trading.
- Price movement is intentionally simple in V1 and depends only on shares bought and sold.
- External stats and sentiment signals are used for bot decision-making, not direct valuation.
- Future pre-match betting market reads may be used as bot/context signals, not direct Stockball price setters.
- Premier League player identity, fixtures, and per-fixture player stats should use API-Football as the V1 canonical provider so player stat observations can link through one provider player ID.
- Player market values may need a separate licensed/commercial source or manual CSV import; direct Transfermarkt scraping should not be the default production path.
- Stockball should keep canonical `players.id` values and store provider IDs in separate mapping/observation tables so players can be reconciled across providers and future imports.
- Weekly versus monthly bot top-ups is still undecided and can be finalized later without changing the core market structure.
- Team and national-team index funds are deferred until after the player market is stable.
