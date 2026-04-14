# Worker Clients Module

## Purpose

Contains HTTP clients used by the worker service to call internal services.

## Responsibilities

- Call the trading engine to execute bot trades.
- Call the trading engine to apply top-up credits.
- Call the trading engine to freeze or unfreeze assets.
- Attach request IDs and idempotency keys to retry-sensitive commands.
- Translate transport errors into retryable job failures.

## Boundaries

- Should not contain synthetic trader strategy logic.
- Should not contain ingestion logic.
- Should not mutate database tables directly when the trading engine owns the operation.
