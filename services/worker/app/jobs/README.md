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
