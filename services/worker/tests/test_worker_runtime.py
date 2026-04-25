from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from app.jobs import (
    JobExecutionResult,
    JobType,
    RetryableJobError,
    TopupJobPayload,
    WorkerJob,
    WorkerJobRunner,
    WorkerProcess,
)
from app.topups import TopupCadence


class FakeQueue:
    def __init__(self, jobs: list[WorkerJob]) -> None:
        self.jobs = list(jobs)

    def dequeue(self, timeout_seconds: int) -> WorkerJob | None:
        if not self.jobs:
            return None
        return self.jobs.pop(0)


class FakeRetryQueue:
    def __init__(self) -> None:
        self.scheduled: list[tuple[WorkerJob, datetime]] = []
        self.moved = 0

    def schedule(self, job: WorkerJob, available_at: datetime) -> None:
        self.scheduled.append((job, available_at))

    def move_due(self, limit: int = 100) -> int:
        return self.moved


class SuccessHandler:
    def handle(self, job: WorkerJob) -> JobExecutionResult:
        return JobExecutionResult(
            job_type=job.job_type,
            handled_at=datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
            successful_items=1,
            skipped_items=0,
            failed_items=0,
        )


class RetryableHandler:
    def handle(self, job: WorkerJob) -> JobExecutionResult:
        result = JobExecutionResult(
            job_type=job.job_type,
            handled_at=datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
            successful_items=0,
            skipped_items=0,
            failed_items=1,
            retryable_failures=1,
        )
        raise RetryableJobError("temporary failure", result)


class WorkerProcessTests(unittest.TestCase):
    def test_run_once_executes_job_without_retry(self) -> None:
        job = WorkerJob.topup(
            TopupJobPayload(
                cadence=TopupCadence.WEEKLY,
                effective_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
            )
        )
        process = WorkerProcess(
            queue=FakeQueue([job]),
            retry_queue=FakeRetryQueue(),
            runner=WorkerJobRunner({JobType.APPLY_TOPUPS: SuccessHandler()}),
            retry_delay_seconds=30,
            max_attempts=5,
            clock=lambda: datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
        )

        handled = process.run_once(block_seconds=0)

        self.assertTrue(handled)

    def test_run_once_schedules_retry_with_incremented_attempt(self) -> None:
        retry_queue = FakeRetryQueue()
        job = WorkerJob.topup(
            TopupJobPayload(
                cadence=TopupCadence.WEEKLY,
                effective_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
            )
        )
        process = WorkerProcess(
            queue=FakeQueue([job]),
            retry_queue=retry_queue,
            runner=WorkerJobRunner({JobType.APPLY_TOPUPS: RetryableHandler()}),
            retry_delay_seconds=30,
            max_attempts=5,
            clock=lambda: datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
        )

        handled = process.run_once(block_seconds=0)

        self.assertTrue(handled)
        self.assertEqual(len(retry_queue.scheduled), 1)
        retried_job, available_at = retry_queue.scheduled[0]
        self.assertEqual(retried_job.attempt, 1)
        self.assertEqual(available_at, datetime(2026, 4, 22, 11, 0, 30, tzinfo=UTC))

    def test_run_once_drops_job_after_retry_exhaustion(self) -> None:
        retry_queue = FakeRetryQueue()
        job = WorkerJob(
            job_type=JobType.APPLY_TOPUPS,
            payload=TopupJobPayload(
                cadence=TopupCadence.WEEKLY,
                effective_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
            ).to_payload(),
            attempt=4,
        )
        process = WorkerProcess(
            queue=FakeQueue([job]),
            retry_queue=retry_queue,
            runner=WorkerJobRunner({JobType.APPLY_TOPUPS: RetryableHandler()}),
            retry_delay_seconds=30,
            max_attempts=5,
            clock=lambda: datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
        )

        handled = process.run_once(block_seconds=0)

        self.assertTrue(handled)
        self.assertEqual(retry_queue.scheduled, [])


if __name__ == "__main__":
    unittest.main()
