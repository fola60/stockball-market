# Trading Engine Instruments Module

## Purpose

Owns tradable instrument state inside the trading engine.

An instrument is anything Stockball can trade. In V1, the only implemented instrument type is `PLAYER_SHARE`, which represents a Premier League player share. Derivatives are not implemented yet, but this module should be designed so future instrument types can be added without rewriting order execution.

## Responsibilities

- Read instrument records needed for execution.
- Store and update current instrument price.
- Store shares outstanding, the reference price, net shares purchased, and the configurable
  full-supply price multiplier used by the curve.
- Store tradability status.
- Link `PLAYER_SHARE` instruments to player records.
- Provide instrument state to `execution`, `price_impact`, and `freezes`.

## V1 Instrument Type

- `PLAYER_SHARE`: a tradable share linked to one Premier League player.

## Future Instrument Types

- `TEAM_INDEX`
- `PLAYER_OPTION`
- `PLAYER_FUTURE`
- `MATCH_CONTRACT`
- `SEASON_PERFORMANCE_CONTRACT`

## Boundaries

- May update current price and net shares purchased only as part of trading-engine flows.
- Must not ingest player data from external providers.
- Must not decide bot behavior.
- Must not expose public instrument APIs directly; the API service does that.
- Must not implement derivative behavior until a dedicated derivative milestone exists.
