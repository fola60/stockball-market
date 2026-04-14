# Trading Engine Assets Module

## Purpose

Owns tradable player asset state inside the trading engine.

## Responsibilities

- Read player asset records needed for execution.
- Store and update current asset price.
- Store shares outstanding and `price_impact_unit`.
- Store tradability status.
- Link tradable assets to player records.
- Provide asset state to `execution`, `price_impact`, and `freezes`.

## Boundaries

- May update current asset price only as part of trading-engine flows.
- Must not ingest player data from external providers.
- Must not decide bot behavior.
- Must not expose public asset APIs directly; the API service does that.
