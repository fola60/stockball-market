# Trading Engine Module Rules

## Purpose

This document defines ownership boundaries for Rust modules inside the trading engine.

The trading engine is the only service allowed to execute trades or mutate market-critical state. Inside the trading engine, each module must still keep a narrow scope so cash, positions, prices, orders, and audit records cannot be changed through multiple competing paths.

## Global Rules

- All buy/sell execution must go through `execution`.
- All cash changes must go through `ledger`.
- All position quantity changes must go through `positions`.
- All instrument price changes must go through `instruments`, using values calculated by `price_impact`.
- All price history records must go through `snapshots`.
- All retry-sensitive commands must go through `idempotency`.
- All execution flows must be transaction-safe.
- No module should bypass another module's audit or validation responsibility for convenience.

## Call Pattern

Trading-engine modules are Rust modules inside one Rust service. They do not call each other over HTTP.

The normal write flow is:

```text
internal HTTP route
  -> execution
  -> orders / idempotency / instruments / portfolios / ledger / positions / price_impact / snapshots
```

`execution` is the high-level orchestrator for trades. It opens the transaction, calls module functions in the correct order, passes values between modules, and commits or rolls back the transaction.

Domain modules may call small helper functions from other modules only when that dependency is part of their ownership boundary. For example, `ledger` may use a restricted portfolio balance update helper because `portfolios` stores cached cash balance. However, modules should not chain together a full trade flow themselves.

Rules:

- `execution` coordinates multi-module trade workflows.
- Domain modules expose narrow functions for their own state.
- Domain modules should not call `execution`.
- Domain modules should not call unrelated modules to produce side effects.
- Read helpers may be shared when they do not mutate state.
- Write helpers must stay restricted to their owning workflow.

## Transaction Rules

Trade execution must happen in one database transaction.

For an order execution, the transaction must include:

- idempotency key check/claim
- order creation or status update
- instrument tradability check
- instrument price read/update
- portfolio/account validation
- cash ledger entry creation
- cached portfolio cash balance update
- position quantity update
- trade record creation
- price snapshot creation

The implementation must prevent concurrent orders from reading the same cash/price state and overwriting each other. Use row-level locks, atomic updates, or an explicitly documented equivalent.

## Read/Write Ownership Matrix

| Module | May Read | May Write | Must Not Write |
| --- | --- | --- | --- |
| `execution` | all trade-required state through module APIs | no direct table writes unless routing through owned modules | raw cash, positions, instrument prices, snapshots, idempotency state directly |
| `orders` | orders, instrument IDs, portfolio IDs, account IDs supplied in commands | order records and order status | cash, positions, instrument prices, ledger entries, snapshots |
| `idempotency` | idempotency keys | idempotency key state and stored response metadata | orders, trades, cash, positions, instrument prices |
| `instruments` | instruments and player-share terms | current instrument price/status only through execution-approved flows | cash, positions, trades, ledger entries, snapshots |
| `price_impact` | input values passed by caller | nothing; pure calculation module | all database tables |
| `portfolios` | portfolios and cached cash balance | cached `cash_balance` only through ledger-restricted helper | ledger entries, positions, instrument prices, trades |
| `ledger` | portfolios and ledger entries | cash ledger entries and cached portfolio cash balance | positions, instrument prices, trades |
| `positions` | positions | position quantity rows | cash, ledger entries, instrument prices, trades |
| `snapshots` | price snapshots and identifying trade/instrument values | price snapshot rows | current instrument price, cash, positions, trades |
| `freezes` | instrument freeze/status state | freeze/status state | cash, positions, trades, ledger entries |

If a write does not appear in a module's "May Write" column, that module must not perform it.

## `execution`

Owns orchestration of buy/sell execution.

Allowed:

- Coordinate calls to `orders`, `idempotency`, `instruments`, `freezes`, `ledger`, `positions`, `price_impact`, and `snapshots`.
- Define the buy/sell transaction flow.
- Return complete execution results to callers.
- Pass transaction-scoped executors into module functions.
- Pass values between modules, such as execution price, gross amount, quantity, and new instrument price.

Not allowed:

- Directly mutate cash without `ledger`.
- Directly mutate position quantity without `positions`.
- Directly calculate price movement without `price_impact`.
- Directly write price history without `snapshots`.
- Contain external ingestion, bot strategy, or public API logic.

## `orders`

Owns order commands and order records.

Allowed:

- Validate order command shape.
- Validate side and quantity.
- Read order records.
- Create order records.
- Mark orders as filled, rejected, or failed.
- Store request IDs needed for idempotent execution.

Not allowed:

- Execute trades.
- Mutate cash balances.
- Mutate positions.
- Mutate instrument prices.
- Decide synthetic trader behavior.

## `idempotency`

Owns safe retries for non-repeatable commands.

Allowed:

- Claim idempotency keys.
- Read idempotency key records.
- Detect duplicate requests.
- Store completed response metadata where needed.
- Return or support returning the original result for duplicate commands.

Not allowed:

- Decide order validity.
- Mutate cash, positions, prices, or trades directly.
- Replace database transaction safety.

## `instruments`

Owns tradable instrument state.

Allowed:

- Read instrument records.
- Check instrument type and trading status.
- Provide current price to execution.
- Persist current price updates only inside execution-approved trade flows.
- Store V1 `PLAYER_SHARE` terms such as `price_impact_unit` until those terms are split out.

Not allowed:

- Execute trades.
- Mutate user positions.
- Mutate cash balances.
- Create price snapshots.
- Ingest player/provider data.
- Implement derivative behavior in V1.

## `price_impact`

Owns price movement calculation.

Allowed:

- Calculate old price to new price changes.
- Apply the V1 formula: buys increase price by `quantity * price_impact_unit`; sells decrease price by `quantity * price_impact_unit`.
- Enforce future price movement guardrails when added.

Not allowed:

- Persist instrument prices.
- Create trades.
- Create snapshots.
- Read social/stat signals directly.
- Execute orders.

## `portfolios`

Owns portfolio container state and cached cash-balance storage.

Allowed:

- Read portfolios.
- Verify a portfolio belongs to an account.
- Read cached `cash_balance`.
- Provide low-level cached cash balance update helpers only if they are inaccessible outside the ledger path.

Not allowed:

- Publicly expose direct cash mutation functions.
- Change cash without a corresponding ledger entry.
- Own cash movement reasons.
- Mutate positions.
- Create trades.
- Calculate price impact.

Rule:

`portfolios.cash_balance` is a cached balance. The `ledger` module owns the business action that changes it.

Any function that changes `portfolios.cash_balance` must be private or restricted so only `ledger` can call it. It must not be exported as a general trading-engine helper.

## `ledger`

Owns all cash movement auditability.

Allowed:

- Debit cash for buys.
- Read portfolio cash state needed to apply cash deltas.
- Read ledger entries for audit/history views.
- Credit cash for sells.
- Credit scheduled top-ups.
- Record admin adjustments or reversals when those features exist.
- Insert immutable `cash_ledger_entries`.
- Update cached `portfolios.cash_balance` transactionally with the ledger entry.
- Reject debits that would make cash negative.

Not allowed:

- Mutate positions.
- Mutate instrument prices.
- Execute full trades.
- Bypass idempotency for retry-sensitive top-ups or adjustments.

Rule:

No cash balance change is valid unless a matching ledger entry is written in the same transaction.

`ledger` may call restricted portfolio helpers to update cached cash balance, but other modules must call `ledger` instead of those helpers.

## `positions`

Owns account exposure to instruments.

Allowed:

- Read position quantity.
- Create a position on first buy.
- Increase long position quantity after buys.
- Decrease long position quantity after sells.
- Reject sells larger than owned quantity.

Not allowed:

- Mutate cash.
- Create ledger entries.
- Mutate instrument prices.
- Create trades.
- Implement shorting, margin, or derivatives in V1.

Rule:

V1 positions are long-only `PLAYER_SHARE` quantities.

## `snapshots`

Owns price history.

Allowed:

- Record price snapshots after price-changing trades.
- Link snapshots to trades where applicable.
- Store old price, new price, reason, instrument, and timestamp.

Not allowed:

- Decide price movement.
- Mutate current instrument price.
- Execute trades.

## `freezes`

Owns market halt enforcement.

Allowed:

- Apply freeze state to instruments.
- Remove freeze state from instruments.
- Check whether an instrument is frozen.
- Reject or help reject orders for frozen instruments.

Not allowed:

- Detect external fixture events directly.
- Execute trades.
- Mutate cash or positions.

## Cross-Service Rules

- API service can authenticate users and provision tagged synthetic trader accounts, but cannot execute trades.
- Worker service can configure synthetic trader strategies and request bot trades, but cannot execute trades.
- Worker service can decide a top-up is due, but the trading engine ledger applies the credit.
- Admin UI reads through the API service only.

## V1 Non-Goals

- No derivatives.
- No margin.
- No short selling.
- No options or futures.
- No external stat/sentiment repricing.
- No true matching engine.
