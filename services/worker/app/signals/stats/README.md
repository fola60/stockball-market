# Worker Signals Stats Module

## Purpose

Calculates football-performance signals from ingested stats and availability data.

## Responsibilities

- Interpret player form.
- Track minutes, goals, assists, clean-sheet relevance, cards, injuries, and suspensions once data exists.
- Produce normalized stat signal observations for bot strategies.

## Boundaries

- Does not ingest provider data directly.
- Does not directly change prices.
- Does not execute trades.
- Provides signal inputs to `synthetic_traders`.
