# Trading Engine Portfolios Module

## Purpose

Owns portfolio state and holding mutations inside the trading engine.

## Responsibilities

- Read portfolio cash and holdings during execution.
- Increase holdings after buy trades.
- Decrease holdings after sell trades.
- Prevent users from selling more shares than they own.
- Support portfolio valuation once implemented.
- Maintain average cost or cost basis once implemented.

## Boundaries

- Cash audit entries belong to `ledger`.
- Holding changes caused by trades belong here.
- Read APIs for portfolio display belong to the API service.
- The worker service must not mutate holdings directly.
