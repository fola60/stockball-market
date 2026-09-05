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


class FakeReporter:
    def __init__(self) -> None:
        self.events = []
    def mark_running(self, run_id, attempt): self.events.append(("running", run_id, attempt))
    def mark_succeeded(self, run_id, result, elapsed_ms): self.events.append(("succeeded", run_id, result.successful_items))
    def mark_retrying(self, run_id, attempt, error, result): self.events.append(("retrying", run_id, attempt))
    def mark_failed(self, run_id, error, result=None): self.events.append(("failed", run_id, error))


class FakeActiveJobReporter:
    def __init__(self) -> None:
        self.events = []

    def mark_job_started(self, job, started_at):
        self.events.append(("started", job.job_type, started_at))

    def mark_job_finished(self, job):
        self.events.append(("finished", job.job_type))


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
    def test_active_job_is_reported_and_cleared(self) -> None:
        active_reporter = FakeActiveJobReporter()
        job = WorkerJob(JobType.APPLY_TOPUPS, {})
        process = WorkerProcess(
            queue=FakeQueue([job]),
            retry_queue=FakeRetryQueue(),
            runner=WorkerJobRunner({JobType.APPLY_TOPUPS: SuccessHandler()}),
            retry_delay_seconds=30,
            max_attempts=5,
            active_job_reporter=active_reporter,
        )

        process.run_once(0)

        self.assertEqual([event[0] for event in active_reporter.events], ["started", "finished"])

    def test_correlated_operation_reports_running_and_success(self) -> None:
        reporter = FakeReporter()
        run_id = uuid4()
        job = WorkerJob(JobType.APPLY_TOPUPS, {}, operation_run_id=run_id)
        process = WorkerProcess(
            queue=FakeQueue([job]), retry_queue=FakeRetryQueue(),
            runner=WorkerJobRunner({JobType.APPLY_TOPUPS: SuccessHandler()}),
            retry_delay_seconds=30, max_attempts=5, operation_reporter=reporter,
        )
        process.run_once(0)
        self.assertEqual([event[0] for event in reporter.events], ["running", "succeeded"])

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
