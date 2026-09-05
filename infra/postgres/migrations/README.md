# PostgreSQL Migrations

## Purpose

Stores database migration files.

## Responsibilities

- Create and evolve Stockball database tables.
- Seed minimal test data where appropriate.
- Seed reusable synthetic trader strategy profiles where worker defaults need to exist in every environment.
- Preserve repeatable database setup from a clean environment.
- Store betting-market odds observations through deterministic migrations.
- Store X source registries, cursor checkpoints, injury episodes/evidence, and compact
  player availability observations through deterministic migrations.
- Normalize stable betting-market selections and player participants separately from
  append-only odds observations.
- Seed conservative and aggressive `BETTING_MARKET_VALUE` synthetic trader profiles.
- Store audited, one-off synthetic portfolio issuance and dedicated reserve ownership.

## Boundaries

- Migrations define schema and controlled data changes.
- Business logic belongs in services.
- Migration files should be deterministic and reviewable.
