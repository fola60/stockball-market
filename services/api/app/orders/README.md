# API Orders Module

## Purpose

Accepts user-facing buy and sell requests.

## Responsibilities

- Validate the public order request shape.
- Confirm the caller is authenticated.
- Build the internal order execution command.
- Generate or forward an idempotency key.
- Call the trading engine to execute the order.
- Return the trading-engine result to the client.

## Boundaries

- Does not decide final order validity.
- Does not check final cash/share availability.
- Does not fill orders.
- Does not create trades.
- Does not mutate prices, positions, or cash.

Final market validation belongs to the trading engine because synthetic traders and users must go through the same execution path.
