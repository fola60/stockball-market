# PostgreSQL Infrastructure

## Purpose

PostgreSQL is the durable source of truth for Stockball.

## Responsibilities

- Store accounts, players, instruments, portfolios, positions, orders, trades, price snapshots, freezes, fixtures, signals, synthetic trader configs, and audit records.
- Provide migration files under `migrations`.
- Support local and production database setup.

## Boundaries

- The database may be shared for V1, but service-level ownership rules still apply.
- Trading-owned tables should only be mutated through the trading engine.
- Redis must not be used as durable storage.
