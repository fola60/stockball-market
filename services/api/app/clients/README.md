# API Clients Module

## Purpose

Contains HTTP clients used by the API service to call internal services.

## Responsibilities

- Call the trading engine for order execution.
- Call the trading engine for supported admin market commands.
- Normalize internal-service errors into API responses.
- Attach request IDs and idempotency keys where needed.

## Boundaries

- Client modules should not contain market business logic.
- They should translate requests/responses and handle transport concerns only.
- If an action changes trades, prices, balances, or positions, the API must call the trading engine rather than changing the database directly.
