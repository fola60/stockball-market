from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.jobs import JobType, TopupJobPayload
from app.scheduler import InMemoryJobQueue, InMemoryScheduleClaimStore, SchedulerService
from app.topups import TopupCadence


class SchedulerServiceTests(unittest.TestCase):
    def test_schedule_due_jobs_enqueues_topup_jobs_once_per_window(self) -> None:
        queue = InMemoryJobQueue()
        claim_store = InMemoryScheduleClaimStore()
        scheduler = SchedulerService(queue=queue, claim_store=claim_store)
        effective_at = datetime(2026, 4, 22, 15, 30, tzinfo=UTC)

        first_run = scheduler.schedule_due_jobs(effective_at)
        second_run = scheduler.schedule_due_jobs(effective_at)

        self.assertEqual(len(first_run), 2)
        self.assertEqual(len(second_run), 0)
        self.assertEqual(len(queue.jobs), 2)
        self.assertTrue(all(job.job_type is JobType.APPLY_TOPUPS for job in queue.jobs))

        weekly_payload = TopupJobPayload.from_payload(queue.jobs[0].payload)
        monthly_payload = TopupJobPayload.from_payload(queue.jobs[1].payload)
        self.assertEqual(weekly_payload.cadence, TopupCadence.WEEKLY)
        self.assertEqual(monthly_payload.cadence, TopupCadence.MONTHLY)
        self.assertEqual(weekly_payload.effective_at, datetime(2026, 4, 20, 0, 0, tzinfo=UTC))
        self.assertEqual(monthly_payload.effective_at, datetime(2026, 4, 1, 0, 0, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
