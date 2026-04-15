# Trading Engine Price Impact Module

## Purpose

Owns the V1 price movement calculation.

## V1 Rule

- Buy orders increase price by `shares_bought * price_impact_unit`.
- Sell orders decrease price by `shares_sold * price_impact_unit`.

## Responsibilities

- Calculate the next instrument price after a trade.
- Keep price math isolated and testable.
- Enforce future guardrails such as minimum price or maximum movement if added.

## Boundaries

- Stats and sentiment must not call this module directly in V1.
- Signals influence synthetic traders.
- Synthetic traders place trades.
- Trades cause price impact.

This keeps the V1 rule simple: prices move only through executed buy and sell activity.
