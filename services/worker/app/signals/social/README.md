# Worker Signals Social Module

## Purpose

Calculates social and hype signals from ingested social/news data.

## Responsibilities

- Calculate mention volume changes.
- Detect unusual attention spikes.
- Estimate positive/negative sentiment where available.
- Produce normalized social signal observations for bot strategies.

## Boundaries

- Does not fetch external data directly; ingestion modules do that.
- Does not mutate prices.
- Does not execute bot trades.
- Provides signal inputs to `synthetic_traders`.
