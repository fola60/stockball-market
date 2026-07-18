# Worker Scheduler Module

## Purpose

Schedules recurring background work.

## Responsibilities

- Enqueue recurring jobs into Redis.
- Schedule ingestion jobs.
- Schedule synthetic trader ticks.
- Schedule top-up checks.
- Schedule fixture/freeze checks.
- Schedule Twitter injury polling only when its explicit opt-in and policy gate are enabled.

## Boundaries

- Does not run the job body itself.
- Does not contain ingestion, bot, top-up, or trading logic.
- Redis is used as the job queue; PostgreSQL remains the durable source of truth.
