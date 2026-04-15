# Trading Engine Positions Module

## Purpose

Owns account exposure to tradable instruments.

A position is what an account owns or is exposed to for a specific instrument. In V1, positions are long-only `PLAYER_SHARE` quantities. Future derivatives can reuse the position concept for options, futures, contracts, or index exposure without treating everything as simple share ownership.

## Responsibilities

- Read positions during order execution.
- Increase long positions after buy trades.
- Decrease long positions after sell trades.
- Prevent V1 users and bots from selling more `PLAYER_SHARE` quantity than they own.
- Store quantity and instrument reference.
- Defer average entry price and cost-basis accounting until portfolio PnL is implemented.
- Support future position types and exposure calculations when derivative instruments are introduced.

## Boundaries

- Cash audit entries belong to `ledger`.
- Portfolio-level summary and cash balance coordination belong to `portfolios`.
- Position mutations caused by trades belong here.
- Read APIs for position display belong to the API service.
- The worker service must not mutate positions directly.
