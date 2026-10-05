from __future__ import annotations

import unittest
from datetime import timedelta
from uuid import UUID

from app.jobs import IngestPlayersJobPayload, WorkerJob
from app.seeding.worker_jobs import JobRunStatus, WorkerJobDispatcher, WorkerJobFailedError


class FakeStore:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.created: list[tuple[UUID, str, str, dict]] = []
        self.enqueue_failures: list[tuple[UUID, str]] = []

    def create_manual_run(self, run_id, operation_type, job_type, parameters) -> None:
        self.created.append((run_id, operation_type, job_type, dict(parameters)))

    def mark_enqueue_failed(self, run_id, message) -> None:
        self.enqueue_failures.append((run_id, message))

    def get_status(self, run_id) -> JobRunStatus | None:
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return JobRunStatus(
            run_id=run_id,
            status=status,
            successful_items=551 if status == "SUCCEEDED" else 0,
            error_message="FBref denied access" if status == "FAILED" else None,
        )


class FakeQueue:
    def __init__(self, error: Exception | None = None) -> None:
        self.jobs: list[WorkerJob] = []
        self.error = error

    def enqueue(self, job: WorkerJob) -> None:
        if self.error is not None:
            raise self.error
        self.jobs.append(job)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds


def _job() -> WorkerJob:
    return WorkerJob.ingest_players(IngestPlayersJobPayload(league=9, season=2025))


def _dispatcher(store: FakeStore, queue: FakeQueue, clock: FakeClock) -> WorkerJobDispatcher:
    return WorkerJobDispatcher(store, queue, poll_seconds=5, clock=clock, sleep=clock.sleep)


class WorkerJobDispatcherTests(unittest.TestCase):
    def test_records_a_manual_run_enqueues_it_and_waits_for_success(self) -> None:
        store = FakeStore(["QUEUED", "RUNNING", "RUNNING", "SUCCEEDED"])
        queue = FakeQueue()
        clock = FakeClock()

        result = _dispatcher(store, queue, clock).run(
            "INGEST_PLAYERS", _job(), timedelta(minutes=5)
        )

        self.assertEqual(result.status, "SUCCEEDED")
        self.assertEqual(result.successful_items, 551)
        self.assertEqual(clock.sleeps, 3)
        run_id, operation_type, job_type, parameters = store.created[0]
        self.assertEqual(operation_type, "INGEST_PLAYERS")
        self.assertEqual(job_type, "INGEST_PLAYERS")
        self.assertEqual(parameters, {"league": 9, "season": 2025})
        # The worker reports progress against the run row through this id.
        self.assertEqual(queue.jobs[0].operation_run_id, run_id)
        self.assertEqual(result.run_id, run_id)

    def test_failed_run_raises_with_the_worker_error(self) -> None:
        store = FakeStore(["RUNNING", "FAILED"])
        with self.assertRaisesRegex(WorkerJobFailedError, "ended FAILED: FBref denied access"):
            _dispatcher(store, FakeQueue(), FakeClock()).run(
                "INGEST_PLAYERS", _job(), timedelta(minutes=5)
            )

    def test_superseded_run_is_treated_as_a_failure(self) -> None:
        store = FakeStore(["SUPERSEDED"])
        with self.assertRaisesRegex(WorkerJobFailedError, "ended SUPERSEDED"):
            _dispatcher(store, FakeQueue(), FakeClock()).run(
                "INGEST_PLAYERS", _job(), timedelta(minutes=5)
            )

    def test_unfinished_run_times_out_and_points_at_the_worker(self) -> None:
        store = FakeStore(["QUEUED"])
        clock = FakeClock()
        with self.assertRaisesRegex(
            WorkerJobFailedError, r"did not finish within 60s \(status QUEUED\).*ingestion worker"
        ):
            _dispatcher(store, FakeQueue(), clock).run(
                "INGEST_PLAYERS", _job(), timedelta(seconds=60)
            )
        self.assertEqual(clock.now, 60)

    def test_enqueue_failure_marks_the_run_failed_and_reraises(self) -> None:
        store = FakeStore(["QUEUED"])
        with self.assertRaisesRegex(ConnectionError, "redis down"):
            _dispatcher(store, FakeQueue(ConnectionError("redis down")), FakeClock()).run(
                "INGEST_PLAYERS", _job(), timedelta(minutes=5)
            )
        run_id = store.created[0][0]
        self.assertEqual(store.enqueue_failures[0][0], run_id)
        self.assertIn("redis down", store.enqueue_failures[0][1])


if __name__ == "__main__":
    unittest.main()
