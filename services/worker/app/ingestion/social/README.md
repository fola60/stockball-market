# Worker Ingestion Social Module

## Purpose

Future module for ingesting raw social attention data.

## Responsibilities

- Fetch mention counts, posts, or engagement data from approved social/search sources.
- Match social observations to players.
- Store source, observed time, raw counts, and normalized references.
- Preserve enough raw context for `signals/social` to calculate hype and sentiment signals.

## Boundaries

- Does not calculate final trading decisions.
- Does not directly mutate prices.
- Signal interpretation belongs to `services/worker/app/signals/social`.
