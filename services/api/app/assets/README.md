# API Assets Module

## Purpose

Provides read-focused API access to player assets and current market data.

## Responsibilities

- List tradable player assets.
- Show an asset's current price, player identity, status, and freeze state.
- Show price history by reading price snapshots.
- Support market overview screens such as top movers or frozen assets.

## Boundaries

- May read asset and price snapshot data.
- Must not update current prices.
- Must not create assets from ingestion data.
- Asset price changes belong to the trading engine.
- Asset creation from external player data is coordinated by the worker and trading engine.
