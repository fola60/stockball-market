# Worker Application Modules

## Purpose

Contains worker modules for scheduled jobs, ingestion, bot decisions, market seeding, and top-up scheduling.

## Modules

- `entrypoints`: CLI command table, scheduler/job-worker process wiring, and service factories.
- `scheduler`: recurring job scheduling.
- `jobs`: executable job handlers.
- `ingestion`: external data intake.
- `synthetic_traders`: bot strategy decisions.
- `match_freezes`: match-day trading freeze reconciliation.
- `seeding`: one-off pre-market valuation, fleet sizing, and initial share supply.
- `topups`: recurring credit eligibility.
- `clients`: internal service clients.

## Boundary Rule

The worker can decide that work should happen, but market-critical mutations must go through the trading engine.
