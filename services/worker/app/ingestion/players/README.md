# Worker Ingestion Players Module

## Purpose

Ingests Premier League player identity and squad data.

## Responsibilities

- Fetch Premier League squads.
- Store player names, clubs, positions, nationality, age, and provider IDs.
- Maintain canonical player records.
- Support player-to-`PLAYER_SHARE` instrument creation during market seeding.

## Boundaries

- Does not create trades.
- Does not mutate positions or balances.
- Does not decide bot behavior.
- Should preserve external provider IDs for later reconciliation.
