# Worker Ingestion Fixtures Module

## Purpose

Ingests Premier League fixture and match-status data.

## Responsibilities

- Fetch upcoming fixtures.
- Store kickoff times, teams, and fixture IDs.
- Track lineup lock, match start, match end, and settlement status when available.
- Provide fixture facts used by freeze jobs.

## Boundaries

- Does not freeze assets directly in the database.
- Fixture events should trigger worker jobs that call the trading engine freeze commands.
- Trading halt enforcement belongs to `trading-engine/freezes`.
