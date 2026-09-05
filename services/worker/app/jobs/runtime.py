from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol
from time import monotonic

from app.jobs.handlers import RetryableJobError, UnknownJobError, WorkerJobRunner
from app.jobs.models import WorkerJob


class BlockingJobQueue(Protocol):
    def dequeue(self, timeout_seconds: int) -> WorkerJob | None: ...


class RetryQueue(Protocol):
    def schedule(self, job: WorkerJob, available_at: datetime) -> None: ...

    def move_due(self, limit: int = 100) -> int: ...


class OperationRunReporter(Protocol):
    def mark_running(self, run_id, attempt: int) -> None: ...
    def mark_succeeded(self, run_id, result, elapsed_ms: int) -> None: ...
    def mark_retrying(self, run_id, attempt: int, error: str, result) -> None: ...
    def mark_failed(self, run_id, error: str, result=None) -> None: ...


class ActiveJobReporter(Protocol):
    def mark_job_started(self, job: WorkerJob, started_at: datetime) -> None: ...
    def mark_job_finished(self, job: WorkerJob) -> None: ...


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
    operation_reporter: OperationRunReporter | None = None
    active_job_reporter: ActiveJobReporter | None = None

    def run_once(self, block_seconds: int) -> bool:
        moved_retry_count = self.retry_queue.move_due()
        if moved_retry_count:
            self.logger.info("moved %s retry jobs back to the main queue", moved_retry_count)

        job = self.queue.dequeue(block_seconds)
        if job is None:
            return False

        started_at = self.clock()
        started = monotonic()
        if self.active_job_reporter is not None:
            self.active_job_reporter.mark_job_started(job, started_at)
        try:
            return self._run_job(job, started)
        finally:
            if self.active_job_reporter is not None:
                self.active_job_reporter.mark_job_finished(job)

    def _run_job(self, job: WorkerJob, started: float) -> bool:
        if job.operation_run_id is not None and self.operation_reporter is not None:
            self.operation_reporter.mark_running(job.operation_run_id, job.attempt)
        try:
            result = self.runner.run(job)
        except RetryableJobError as exc:
            self._handle_retryable_failure(job, exc)
            return True
        except UnknownJobError as exc:
            self.logger.exception("dropping unknown worker job type %s", job.job_type.value)
            self._mark_failed(job, str(exc))
            return True
        except Exception as exc:
            self.logger.exception(
                "worker job %s failed with an unexpected non-retryable error",
                job.job_type.value,
            )
            self._mark_failed(job, str(exc))
            return True

        elapsed_ms = round((monotonic() - started) * 1000)
        if job.operation_run_id is not None and self.operation_reporter is not None:
            self.operation_reporter.mark_succeeded(job.operation_run_id, result, elapsed_ms)

        self.logger.info(
            "completed worker job %s run_id=%s attempt=%s elapsed_ms=%s success=%s skipped=%s failed=%s metrics=%s",
            job.job_type.value,
            job.operation_run_id,
            job.attempt,
            elapsed_ms,
            result.successful_items,
            result.skipped_items,
            result.failed_items,
            dict(result.metrics),
            extra={"operation_run_id": str(job.operation_run_id) if job.operation_run_id else None,
                   "elapsed_ms": elapsed_ms, "metrics": dict(result.metrics)},
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
            self._mark_failed(job, str(error), error.result)
            return

        available_at = self.clock() + timedelta(seconds=self.retry_delay_seconds)
        self.retry_queue.schedule(job.with_attempt(next_attempt), available_at)
        if job.operation_run_id is not None and self.operation_reporter is not None:
            self.operation_reporter.mark_retrying(
                job.operation_run_id, next_attempt, str(error), error.result
            )
        self.logger.warning(
            "scheduled retry for job %s attempt=%s available_at=%s",
            job.job_type.value,
            next_attempt,
            available_at.isoformat(),
        )

    def _mark_failed(self, job: WorkerJob, error: str, result=None) -> None:
        if job.operation_run_id is not None and self.operation_reporter is not None:
            self.operation_reporter.mark_failed(job.operation_run_id, error, result)
