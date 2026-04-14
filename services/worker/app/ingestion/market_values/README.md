# Worker Ingestion Market Values Module

## Purpose

Ingests external player market values used for initial Stockball price seeding.

## Responsibilities

- Fetch or scrape player market-value data.
- Match external player records to canonical players.
- Store source, value, currency, and observed timestamp.
- Provide initial valuation anchors for player asset creation.

## Boundaries

- Does not directly set live trading prices after V1 seeding.
- Does not decide price movement.
- Price movement after seeding belongs to executed trades in the trading engine.
