from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import redis

from app.jobs.models import JobType, WorkerJob


class RedisJobQueue:
    def __init__(
        self,
        redis_url: str,
        queue_name: str,
        client: redis.Redis | None = None,
    ) -> None:
        self._queue_name = queue_name
        self._client = client or redis.Redis.from_url(redis_url, decode_responses=True)

    def enqueue(self, job: WorkerJob) -> None:
        self._client.rpush(self._queue_name, _serialize_job(job))

    def dequeue(self, timeout_seconds: int) -> WorkerJob | None:
        item = self._client.blpop(self._queue_name, timeout=timeout_seconds)
        if item is None:
            return None

        _, raw_message = item
        return _deserialize_job(raw_message)


class JobRoutingQueue:
    """Routes scheduled jobs to isolated queues without changing message format."""

    def __init__(
        self,
        *,
        trading_queue: RedisJobQueue,
        ingestion_queue: RedisJobQueue,
    ) -> None:
        self._trading_queue = trading_queue
        self._ingestion_queue = ingestion_queue

    def enqueue(self, job: WorkerJob) -> None:
        queue = (
            self._trading_queue
            if job.job_type in {JobType.APPLY_TOPUPS, JobType.SYNTHETIC_TRADER_TICK}
            else self._ingestion_queue
        )
        queue.enqueue(job)


class RedisRetryQueue:
    def __init__(
        self,
        redis_url: str,
        retry_queue_name: str,
        main_queue_name: str,
        client: redis.Redis | None = None,
    ) -> None:
        self._retry_queue_name = retry_queue_name
        self._main_queue_name = main_queue_name
        self._client = client or redis.Redis.from_url(redis_url, decode_responses=True)

    def schedule(self, job: WorkerJob, available_at: datetime) -> None:
        self._client.zadd(
            self._retry_queue_name,
            {_serialize_job(job): available_at.timestamp()},
        )

    def move_due(self, limit: int = 100) -> int:
        moved = 0
        now = datetime.now().timestamp()

        while moved < limit:
            item = self._client.zpopmin(self._retry_queue_name, count=1)
            if not item:
                break

            raw_message, due_score = item[0]
            due_timestamp = float(due_score)
            if due_timestamp > now:
                self._client.zadd(self._retry_queue_name, {raw_message: due_timestamp})
                break

            self._client.rpush(self._main_queue_name, raw_message)
            moved += 1

        return moved


class RedisScheduleClaimStore:
    def __init__(
        self,
        redis_url: str,
        key_prefix: str,
        ttl_seconds: int,
        client: redis.Redis | None = None,
    ) -> None:
        self._key_prefix = key_prefix.rstrip(":")
        self._ttl_seconds = ttl_seconds
        self._client = client or redis.Redis.from_url(redis_url, decode_responses=True)

    def claim(self, schedule_name: str, window_key: str) -> bool:
        claim_key = f"{self._key_prefix}:{schedule_name}:{window_key}"
        created = self._client.set(claim_key, "1", ex=self._ttl_seconds, nx=True)
        return bool(created)


def _serialize_job(job: WorkerJob) -> str:
    return json.dumps(job.to_message(), sort_keys=True, separators=(",", ":"))


def _deserialize_job(raw_message: str | bytes) -> WorkerJob:
    if isinstance(raw_message, bytes):
        payload: Any = json.loads(raw_message.decode("utf-8"))
    else:
        payload = json.loads(raw_message)
    return WorkerJob.from_message(payload)
