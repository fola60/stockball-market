# Admin UI

## Purpose

Internal dashboard for operating and inspecting the Stockball market.

## Responsibilities

- Show instruments, prices, and price history.
- Show portfolios, positions, orders, and trades.
- Show synthetic trader activity.
- Show market freezes and fixture-related status.
- Show ingestion jobs, signal health, and failures.

## Boundaries

- Talks only to the API service.
- Does not call the trading engine directly.
- Does not connect directly to PostgreSQL or Redis.
- Does not contain market business logic.
