# Worker Synthetic Traders Module

## Purpose

Owns synthetic trader strategy configuration and decision logic.

Synthetic traders are tagged accounts that behave like users but are controlled by the system. The API/accounts boundary provisions the account; this module configures strategy and decides trades after the account exists.

## Responsibilities

- Manage synthetic trader strategy configuration.
- Decide which bots should buy, sell, or hold.
- Apply strategy families such as social/hype-driven, stats-driven, market-watching, and noise traders.
- Respect bot position limits and risk settings.
- Send trade decisions to the trading engine through the worker client.

## Boundaries

- Does not execute trades directly.
- Does not provision account identities directly.
- Does not mutate prices, positions, or cash directly.
- Bot trades must go through the same trading-engine order endpoint as user trades.
- Bot accounts receive top-ups through the same top-up flow as normal users.
