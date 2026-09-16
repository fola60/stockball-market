# Trading Engine Execution Module

## Purpose

Orchestrates the complete execution of buy and sell orders.

## Responsibilities

- Coordinate order validation, freeze checks, portfolio checks, ledger updates, position updates, trade creation, price impact, and snapshots.
- Quote orders from the price curve and charge the exact average price across the curved movement.
- Preserve twelve-decimal monetary precision through execution and ledger storage.
- Ensure buy and sell flows happen transactionally.
- Return a complete execution result to the caller.

## Buy Flow

- Check idempotency.
- Check instrument exists and is tradable.
- Check instrument is not frozen.
- Check portfolio has enough cash.
- Debit cash through `ledger`.
- Increase positions through `positions`.
- Record trade.
- Advance net buying pressure and price through `price_impact`.
- Record price snapshot through `snapshots`.

## Sell Flow

- Check idempotency.
- Check instrument exists and is tradable.
- Check instrument is not frozen.
- Check portfolio owns enough shares.
- Reduce positions through `positions`.
- Credit cash through `ledger`.
- Record trade.
- Reduce net buying pressure and price through `price_impact`.
- Record price snapshot through `snapshots`.

## Boundaries

- Should coordinate domain modules rather than hiding their responsibilities.
- Should not contain external data, bot strategy, or public API logic.
