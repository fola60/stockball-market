from __future__ import annotations

import json
from datetime import datetime

import redis

from app.jobs.models import WorkerJob


SCHEDULE_OVERRIDES_KEY = "stockball:dev:schedule-overrides"
SCHEDULER_HEARTBEAT_KEY = "stockball:dev:scheduler-heartbeat"
WORKER_ACTIVE_JOB_KEY = "stockball:dev:worker:active-job"


class RedisProcessState:
    def __init__(self, redis_url: str, scheduler_heartbeat_ttl_seconds: int = 180) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._scheduler_heartbeat_ttl_seconds = scheduler_heartbeat_ttl_seconds

    def is_enabled(self, schedule_name: str, default: bool) -> bool:
        override = self._client.hget(SCHEDULE_OVERRIDES_KEY, schedule_name)
        return default if override is None else override == "1"

    def record_scheduler_heartbeat(
        self,
        checked_at: datetime,
        scheduled_names: tuple[str, ...],
    ) -> None:
        self._client.setex(
            SCHEDULER_HEARTBEAT_KEY,
            self._scheduler_heartbeat_ttl_seconds,
            json.dumps(
                {
                    "checked_at": checked_at.isoformat(),
                    "scheduled_names": list(scheduled_names),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def mark_job_started(self, job: WorkerJob, started_at: datetime) -> None:
        self._client.set(
            WORKER_ACTIVE_JOB_KEY,
            json.dumps(
                {
                    "job_type": job.job_type.value,
                    "payload": dict(job.payload),
                    "attempt": job.attempt,
                    "operation_run_id": (
                        str(job.operation_run_id) if job.operation_run_id else None
                    ),
                    "started_at": started_at.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def mark_job_finished(self, job: WorkerJob) -> None:
        self._client.delete(WORKER_ACTIVE_JOB_KEY)
