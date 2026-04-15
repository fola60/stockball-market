# API Instruments Module

## Purpose

Provides read-focused API access to tradable instruments and current market data.

In V1, the API only exposes `PLAYER_SHARE` instruments. Product copy may call these "player assets" or "player shares", but the internal API model should use instruments for extensibility.

## Responsibilities

- List tradable instruments.
- Show an instrument's current price, instrument type, player identity where applicable, status, and freeze state.
- Show price history by reading price snapshots.
- Support market overview screens such as top movers or frozen instruments.

## Boundaries

- May read instrument and price snapshot data.
- Must not update current prices.
- Must not create instruments from ingestion data.
- Instrument price changes belong to the trading engine.
- `PLAYER_SHARE` instrument creation from external player data is coordinated by the worker and trading engine.
- Must not expose or imply derivatives support until derivative instruments are implemented.
