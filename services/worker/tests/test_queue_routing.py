from __future__ import annotations

import unittest

from app.jobs import JobType, WorkerJob
from app.queue import JobRoutingQueue


class RecordingQueue:
    def __init__(self) -> None:
        self.jobs: list[WorkerJob] = []

    def enqueue(self, job: WorkerJob) -> None:
        self.jobs.append(job)


class JobRoutingQueueTests(unittest.TestCase):
    def test_routes_trading_jobs_away_from_ingestion_jobs(self) -> None:
        trading = RecordingQueue()
        ingestion = RecordingQueue()
        queue = JobRoutingQueue(trading_queue=trading, ingestion_queue=ingestion)

        queue.enqueue(WorkerJob(JobType.SYNTHETIC_TRADER_TICK, {}))
        queue.enqueue(WorkerJob(JobType.APPLY_TOPUPS, {}))
        queue.enqueue(WorkerJob(JobType.INGEST_SOCIAL_FEEDS, {}))

        self.assertEqual(
            [job.job_type for job in trading.jobs],
            [JobType.SYNTHETIC_TRADER_TICK, JobType.APPLY_TOPUPS],
        )
        self.assertEqual(
            [job.job_type for job in ingestion.jobs],
            [JobType.INGEST_SOCIAL_FEEDS],
        )


if __name__ == "__main__":
    unittest.main()
