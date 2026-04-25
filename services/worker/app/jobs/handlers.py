from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Mapping, Protocol

from app.jobs.models import JobExecutionResult, JobType, TopupJobPayload, WorkerJob
from app.topups import TopupService


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobHandler(Protocol):
    def handle(self, job: WorkerJob) -> JobExecutionResult: ...


class UnknownJobError(Exception):
    pass


class RetryableJobError(Exception):
    def __init__(self, message: str, result: JobExecutionResult) -> None:
        self.result = result
        super().__init__(message)


@dataclass(frozen=True)
class TopupJobHandler:
    topup_service: TopupService
    clock: Callable[[], datetime] = _utc_now

    def handle(self, job: WorkerJob) -> JobExecutionResult:
        if job.job_type is not JobType.APPLY_TOPUPS:
            raise UnknownJobError(f"top-up handler cannot process {job.job_type.value}")

        payload = TopupJobPayload.from_payload(job.payload)
        result = self.topup_service.apply_topups(payload.cadence, payload.effective_at)
        job_result = JobExecutionResult(
            job_type=job.job_type,
            handled_at=self.clock(),
            successful_items=result.applied_count,
            skipped_items=result.skipped_count,
            failed_items=result.failed_count,
            retryable_failures=result.retryable_failure_count,
        )
        if result.has_retryable_failures:
            raise RetryableJobError(
                "top-up job encountered retryable trading-engine failures",
                job_result,
            )
        return job_result


class WorkerJobRunner:
    def __init__(self, handlers: Mapping[JobType, JobHandler]) -> None:
        self._handlers = dict(handlers)

    def run(self, job: WorkerJob) -> JobExecutionResult:
        handler = self._handlers.get(job.job_type)
        if handler is None:
            raise UnknownJobError(f"no handler registered for {job.job_type.value}")
        return handler.handle(job)
