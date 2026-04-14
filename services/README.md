# Services

## Purpose

Contains independently runnable Stockball services.

## Services

- `api`: public/admin API service.
- `trading-engine`: consistency-critical market execution service.
- `worker`: scheduled jobs, ingestion, signals, and synthetic trader decisions.
- `admin-ui`: internal dashboard.

## Boundary Rule

Services may be written in different languages, but they must communicate through explicit contracts rather than reaching into each other's business logic.
