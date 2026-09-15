from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

import redis

SCHEDULE_OVERRIDES_KEY = "stockball:dev:schedule-overrides"
SCHEDULER_HEARTBEAT_KEY = "stockball:dev:scheduler-heartbeat"
WORKER_ACTIVE_JOB_KEY = "stockball:dev:worker:active-job"


@dataclass(frozen=True)
class ProcessDefinition:
    name: str
    display_name: str
    job_type: str
    schedule: str
    default_enabled: bool
    payload_mode: str | None = None


def configured_processes() -> tuple[ProcessDefinition, ...]:
    player_hour = int(os.getenv("STOCKBALL_PLAYER_STATS_SCHEDULE_HOUR_UTC", "3"))
    player_league = os.getenv("STOCKBALL_PLAYER_STATS_SCHEDULE_LEAGUE", "9")
    player_season = os.getenv("STOCKBALL_PLAYER_STATS_SCHEDULE_SEASON", "2025")
    bet_interval = int(os.getenv("STOCKBALL_BET365_SCHEDULE_INTERVAL_MINUTES", "15"))
    live_interval = int(os.getenv("STOCKBALL_BET365_LIVE_SCHEDULE_INTERVAL_MINUTES", "1"))
    return (
        ProcessDefinition(
            "social-feed-ingestion",
            "Social feed ingestion",
            "INGEST_SOCIAL_FEEDS",
            "Every scheduler cycle · polls only due subscriptions",
            True,
        ),
        ProcessDefinition(
            "daily-player-stats",
            "Daily player stats",
            "INGEST_PLAYER_STATS",
            f"Daily at {player_hour:02d}:00 UTC · league {player_league} · season {player_season}",
            _bool_env("STOCKBALL_PLAYER_STATS_SCHEDULE_ENABLED", True),
        ),
        ProcessDefinition(
            "bet365-odds",
            "Bet365 pre-match markets",
            "INGEST_BET365_ODDS",
            f"Every {bet_interval} minutes",
            _bool_env("STOCKBALL_BET365_SCHEDULE_ENABLED", False),
            "PRE_MATCH",
        ),
        ProcessDefinition(
            "bet365-live-odds",
            "Bet365 live markets",
            "INGEST_BET365_ODDS",
            f"Every {live_interval} minute{'s' if live_interval != 1 else ''}",
            _bool_env("STOCKBALL_BET365_LIVE_SCHEDULE_ENABLED", False),
            "LIVE",
        ),
        ProcessDefinition(
            "synthetic-trader-ticks",
            "Synthetic trader ticks",
            "SYNTHETIC_TRADER_TICK",
            "Every minute",
            True,
        ),
        ProcessDefinition(
            "weekly-topups",
            "Weekly account top-ups",
            "APPLY_TOPUPS",
            "Every Monday at 00:00 UTC",
            True,
            "WEEKLY",
        ),
        ProcessDefinition(
            "monthly-topups",
            "Monthly account top-ups",
            "APPLY_TOPUPS",
            "First day of each month at 00:00 UTC",
            True,
            "MONTHLY",
        ),
    )


class RedisProcessRegistry:
    def __init__(
        self,
        redis_url: str,
        queue_name: str,
        executable_run_ids: Callable[[list[str]], set[str]] | None = None,
    ) -> None:
        # redis-py's sync and async overloads are indistinguishable to static
        # analyzers; this registry deliberately owns the synchronous client.
        self._client: Any = redis.Redis.from_url(redis_url, decode_responses=True)
        self._queue_name = queue_name
        self._executable_run_ids = executable_run_ids
        self._definitions = {item.name: item for item in configured_processes()}

    def snapshot(self) -> dict[str, Any]:
        overrides = self._client.hgetall(SCHEDULE_OVERRIDES_KEY)
        heartbeat = _json_value(self._client.get(SCHEDULER_HEARTBEAT_KEY))
        active_job = _json_value(self._client.get(WORKER_ACTIVE_JOB_KEY))
        queued_messages = self._client.lrange(self._queue_name, 0, -1)
        queued_jobs = [_job_summary(message) for message in queued_messages]
        correlated_ids = [
            str(job["operation_run_id"])
            for job in queued_jobs
            if job.get("operation_run_id")
        ]
        if self._executable_run_ids is not None and correlated_ids:
            executable_ids = self._executable_run_ids(correlated_ids)
            queued_jobs = [
                job
                for job in queued_jobs
                if not job.get("operation_run_id")
                or str(job["operation_run_id"]) in executable_ids
            ]
        processes = []
        for definition in self._definitions.values():
            enabled = (
                definition.default_enabled
                if definition.name not in overrides
                else overrides[definition.name] == "1"
            )
            processes.append(
                {
                    "name": definition.name,
                    "display_name": definition.display_name,
                    "job_type": definition.job_type,
                    "schedule": definition.schedule,
                    "enabled": enabled,
                    "default_enabled": definition.default_enabled,
                    "running": _matches(definition, active_job),
                    "queued": sum(_matches(definition, job) for job in queued_jobs),
                }
            )
        return {
            "scheduler": {
                "online": heartbeat is not None,
                "last_seen_at": heartbeat.get("checked_at") if heartbeat else None,
                "last_scheduled": heartbeat.get("scheduled_names", []) if heartbeat else [],
            },
            "active_job": active_job,
            "queued_jobs": queued_jobs,
            "processes": processes,
        }

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        if name not in self._definitions:
            raise ValueError(f"unknown recurring process: {name}")
        self._client.hset(SCHEDULE_OVERRIDES_KEY, name, "1" if enabled else "0")
        return next(item for item in self.snapshot()["processes"] if item["name"] == name)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


def _json_value(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else None


def _job_summary(message: str) -> dict[str, Any]:
    parsed = json.loads(message)
    return {
        "job_type": parsed.get("job_type"),
        "payload": parsed.get("payload", {}),
        "attempt": parsed.get("attempt", 0),
        "operation_run_id": parsed.get("operation_run_id"),
    }


def _matches(definition: ProcessDefinition, job: dict[str, Any] | None) -> bool:
    if not job or job.get("job_type") != definition.job_type:
        return False
    if definition.payload_mode is None:
        return True
    payload = job.get("payload") or {}
    return payload.get("mode") == definition.payload_mode or payload.get("cadence") == definition.payload_mode
