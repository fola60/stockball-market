# Worker Jobs Module

## Purpose

Contains executable background job handlers.

Redis stores jobs. This module executes them.

## Responsibilities

- Run ingestion jobs.
- Run synthetic trader ticks.
- Run top-up jobs.
- Run fixture freeze checks.
- Handle retries and failure logging.
- Delegate business work to the correct worker module or service client.

## Boundaries

- Job handlers should orchestrate work, not hide domain logic.
- Retry-sensitive jobs must use idempotency keys when calling the trading engine.
- Important results must be written to PostgreSQL, not only Redis.
- The synthetic trader tick handler delegates strategy and risk decisions to `app.synthetic_traders.service`.
- Synthetic trader jobs must never write orders, trades, positions, ledger entries, or prices directly; they only call the trading-engine client.
