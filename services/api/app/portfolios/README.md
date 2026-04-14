# API Portfolios Module

## Purpose

Provides read APIs for portfolio state.

## Responsibilities

- Show cash balance.
- Show holdings.
- Show portfolio value and PnL once implemented.
- Show trade and ledger history where appropriate.

## Boundaries

- May read portfolio, holding, trade, and ledger data.
- Must not apply cash credits or debits.
- Must not mutate holdings.
- Trade-related updates and top-up credits are applied by the trading engine.
