# Worker Application Modules

## Purpose

Contains worker modules for scheduled jobs, ingestion, signals, bot decisions, and top-up scheduling.

## Modules

- `scheduler`: recurring job scheduling.
- `jobs`: executable job handlers.
- `ingestion`: external data intake.
- `signals`: interpreted observations for strategies.
- `synthetic_traders`: bot strategy decisions.
- `topups`: recurring credit eligibility.
- `clients`: internal service clients.

## Boundary Rule

The worker can decide that work should happen, but market-critical mutations must go through the trading engine.
