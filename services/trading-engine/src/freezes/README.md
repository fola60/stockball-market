# Trading Engine Freezes Module

## Purpose

Owns market-freeze enforcement.

## Responsibilities

- Open and release freezes (`POST /internal/v1/freezes/apply` and `/release`).
- Record each freeze in `instrument_freezes` with its reason and source key.
- Keep `instruments.trading_status` in step: an instrument is `FROZEN` while it has at least
  one open freeze, and returns to `ACTIVE` when the last one is released.
- Reject orders for frozen instruments during execution.

## Freeze Reasons

- `MATCH_DAY`: from lineup lock until post-match settlement. The worker's `CHECK_MARKET_FREEZES`
  job opens these with source key `fixture:<fixture id>` and releases them after settlement.
- `ADMIN_HALT`: a manual trading halt.
- `DATA_ISSUE`: trading paused while market data is corrected.

Because each reason has its own freeze record, releasing a match-day freeze never lifts an
admin halt on the same player.

## Boundaries

- The worker service decides when a fixture's players should be frozen; this module owns the
  freeze records and instrument status.
- Applying and releasing are idempotent, so the worker can safely re-run its reconciliation.
- The API service and worker service must not bypass freeze checks.
