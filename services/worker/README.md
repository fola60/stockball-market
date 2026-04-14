# Worker Service

## Purpose

The worker service runs background and scheduled work.

It owns external data ingestion, synthetic trader decisions, recurring top-up scheduling, and other asynchronous jobs.

## Responsibilities

- Schedule and execute Redis-backed jobs.
- Ingest Premier League player, market-value, fixture, stats, social, and news data.
- Convert raw ingested data into signals for bot strategies.
- Decide synthetic trader actions.
- Send bot trade commands to the trading engine.
- Determine which accounts are due for top-ups.
- Send top-up credit commands to the trading engine.

## Must Not Own

- Trade execution.
- Direct price mutation.
- Direct holding mutation.
- Direct cash mutation.
- Public API authentication.

## Internal Modules

- `scheduler`: schedules recurring jobs.
- `jobs`: job handlers executed by workers.
- `ingestion`: external data intake.
- `signals`: interpreted observations used by bot strategies.
- `synthetic_traders`: bot strategy and decision logic.
- `topups`: determines recurring credit eligibility.
- `clients`: internal service clients.
