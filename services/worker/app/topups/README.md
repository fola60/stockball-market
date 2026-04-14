# Worker Top-Ups Module

## Purpose

Determines which accounts should receive recurring virtual-cash credits.

## Responsibilities

- Decide weekly or monthly top-up eligibility once the cadence is finalized.
- Include both real users and synthetic traders where configured.
- Create deterministic top-up request IDs.
- Send credit commands to the trading engine ledger endpoint.
- Record top-up job/audit state.

## Boundaries

- Does not directly mutate cash balances.
- Does not write ledger entries directly.
- The trading engine `ledger` module applies the credit.
- Idempotency is required so retries cannot double-credit an account.
