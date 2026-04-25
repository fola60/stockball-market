from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol

from app.jobs.handlers import RetryableJobError, UnknownJobError, WorkerJobRunner
from app.jobs.models import WorkerJob


class BlockingJobQueue(Protocol):
    def dequeue(self, timeout_seconds: int) -> WorkerJob | None: ...


class RetryQueue(Protocol):
    def schedule(self, job: WorkerJob, available_at: datetime) -> None: ...

    def move_due(self, limit: int = 100) -> int: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class WorkerProcess:
    queue: BlockingJobQueue
    retry_queue: RetryQueue
    runner: WorkerJobRunner
    retry_delay_seconds: int
    max_attempts: int
    clock: Callable[[], datetime] = _utc_now
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    def run_once(self, block_seconds: int) -> bool:
        moved_retry_count = self.retry_queue.move_due()
        if moved_retry_count:
            self.logger.info("moved %s retry jobs back to the main queue", moved_retry_count)

        job = self.queue.dequeue(block_seconds)
        if job is None:
            return False

        try:
            result = self.runner.run(job)
        except RetryableJobError as exc:
            self._handle_retryable_failure(job, exc)
            return True
        except UnknownJobError:
            self.logger.exception("dropping unknown worker job type %s", job.job_type.value)
            return True
        except Exception:
            self.logger.exception(
                "worker job %s failed with an unexpected non-retryable error",
                job.job_type.value,
            )
            return True

        self.logger.info(
            "completed worker job %s attempt=%s success=%s skipped=%s failed=%s",
            job.job_type.value,
            job.attempt,
            result.successful_items,
            result.skipped_items,
            result.failed_items,
        )
        return True

    def run_forever(self, block_seconds: int) -> None:
        while True:
            self.run_once(block_seconds)

    def _handle_retryable_failure(self, job: WorkerJob, error: RetryableJobError) -> None:
        next_attempt = job.attempt + 1
        if next_attempt >= self.max_attempts:
            self.logger.error(
                "worker job %s exhausted retries at attempt=%s retryable_failures=%s",
                job.job_type.value,
                next_attempt,
                error.result.retryable_failures,
            )
            return

        available_at = self.clock() + timedelta(seconds=self.retry_delay_seconds)
        self.retry_queue.schedule(job.with_attempt(next_attempt), available_at)
        self.logger.warning(
            "scheduled retry for job %s attempt=%s available_at=%s",
            job.job_type.value,
            next_attempt,
            available_at.isoformat(),
        )
