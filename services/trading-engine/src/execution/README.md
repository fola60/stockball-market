# Trading Engine Execution Module

## Purpose

Orchestrates the complete execution of buy and sell orders.

## Responsibilities

- Coordinate order validation, freeze checks, portfolio checks, ledger updates, holdings updates, trade creation, price impact, and snapshots.
- Fill V1 orders against the platform's current quoted asset price.
- Ensure buy and sell flows happen transactionally.
- Return a complete execution result to the caller.

## Buy Flow

- Check idempotency.
- Check asset exists and is tradable.
- Check asset is not frozen.
- Check portfolio has enough cash.
- Debit cash through `ledger`.
- Increase holdings through `portfolios`.
- Record trade.
- Increase price through `price_impact`.
- Record price snapshot through `snapshots`.

## Sell Flow

- Check idempotency.
- Check asset exists and is tradable.
- Check asset is not frozen.
- Check portfolio owns enough shares.
- Reduce holdings through `portfolios`.
- Credit cash through `ledger`.
- Record trade.
- Decrease price through `price_impact`.
- Record price snapshot through `snapshots`.

## Boundaries

- Should coordinate domain modules rather than hiding their responsibilities.
- Should not contain external data, bot strategy, or public API logic.
