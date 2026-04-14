# Redis Infrastructure

## Purpose

Redis provides lightweight infrastructure for background work.

## Responsibilities

- Back scheduled job queues.
- Back retry queues.
- Support short-lived locks where useful.
- Support lightweight cache if needed.

## Boundaries

- Redis is not the source of truth.
- Redis does not execute jobs.
- Worker job handlers execute jobs pulled from Redis.
- Important data must be persisted in PostgreSQL.
