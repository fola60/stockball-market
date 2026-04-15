# Trading Engine Portfolios Module

## Purpose

Owns portfolio state and portfolio-level balance coordination inside the trading engine.

## Responsibilities

- Read portfolio cash and summary state during execution.
- Coordinate portfolio-level cash balance state with `ledger`.
- Support portfolio valuation once implemented.
- Support portfolio-level PnL summaries once implemented.

## Boundaries

- Cash audit entries belong to `ledger`.
- Position changes caused by trades belong to `positions`.
- Read APIs for portfolio display belong to the API service.
- The worker service must not mutate positions directly.
