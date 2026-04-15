# Trading Engine Orders Module

## Purpose

Owns internal order commands and order records.

## Responsibilities

- Validate order command structure.
- Validate side: `BUY` or `SELL`.
- Validate share quantity.
- Create order records.
- Track order status such as filled, rejected, or failed.
- Coordinate with `idempotency` to prevent duplicate order execution.

## Boundaries

- Does not apply price impact directly.
- Does not mutate positions or cash directly.
- Does not contain public API authentication.
- Final execution is coordinated by the `execution` module.
