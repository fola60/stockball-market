# Worker Ingestion Social Module

## Purpose

Social ingestion is provider-specific. Twitter injury/availability ingestion is implemented
under `ingestion/social/twitter` and uses only the approved X API recent-search endpoint.

## Responsibilities

- Fetch mention counts, posts, or engagement data from approved social/search sources.
- Match social observations to players.
- Store source, observed time, raw counts, and normalized references.
- Preserve enough raw context for `signals/social` to calculate hype and sentiment signals.

See `ingestion/social/twitter/README.md` for the opt-in X source registry, rules classifier,
four-stage episode model, policy gate, and availability observation.

## Boundaries

- Does not calculate final trading decisions.
- Does not directly mutate prices.
- Signal interpretation belongs to `services/worker/app/signals/social`.
