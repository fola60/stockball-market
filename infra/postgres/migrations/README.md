# PostgreSQL Migrations

## Purpose

Stores database migration files.

## Responsibilities

- Create and evolve Stockball database tables.
- Seed minimal test data where appropriate.
- Preserve repeatable database setup from a clean environment.

## Boundaries

- Migrations define schema and controlled data changes.
- Business logic belongs in services.
- Migration files should be deterministic and reviewable.
