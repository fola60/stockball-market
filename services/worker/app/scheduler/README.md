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

## Default Plans

- Weekly and monthly top-up windows.
- Synthetic trader ticks every minute.
- Player-stat ingestion once per day at `03:00 UTC` for configured league `9` and season `2025`.
- Optional Bet365 pre-match and live-market ingestion.
- Social feed discovery every scheduler cycle. When any subscription is due, one correlated
  `INGEST_SOCIAL_FEEDS` batch is queued so its aggregate metrics appear in the dev portal Runs
  ledger. The process can be started or paused from the Processes tab.

Daily player-stat ingestion is configured with
`STOCKBALL_PLAYER_STATS_SCHEDULE_ENABLED`,
`STOCKBALL_PLAYER_STATS_SCHEDULE_HOUR_UTC`,
`STOCKBALL_PLAYER_STATS_SCHEDULE_LEAGUE`, and
`STOCKBALL_PLAYER_STATS_SCHEDULE_SEASON`. If the scheduler is unavailable at the configured
hour, the first subsequent poll claims and runs that daily window.

## Boundaries

- Does not run the job body itself.
- Does not contain ingestion, bot, top-up, or trading logic.
- Redis is used as the job queue; PostgreSQL remains the durable source of truth.
