from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.jobs import JobType, SyntheticTraderTickJobPayload, TopupJobPayload
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

        self.assertEqual(len(first_run), 3)
        self.assertEqual(len(second_run), 0)
        self.assertEqual(len(queue.jobs), 3)

        weekly_payload = TopupJobPayload.from_payload(queue.jobs[0].payload)
        monthly_payload = TopupJobPayload.from_payload(queue.jobs[1].payload)
        synthetic_payload = SyntheticTraderTickJobPayload.from_payload(queue.jobs[2].payload)
        self.assertEqual(weekly_payload.cadence, TopupCadence.WEEKLY)
        self.assertEqual(monthly_payload.cadence, TopupCadence.MONTHLY)
        self.assertEqual(queue.jobs[2].job_type, JobType.SYNTHETIC_TRADER_TICK)
        self.assertEqual(weekly_payload.effective_at, datetime(2026, 4, 20, 0, 0, tzinfo=UTC))
        self.assertEqual(monthly_payload.effective_at, datetime(2026, 4, 1, 0, 0, tzinfo=UTC))
        self.assertEqual(synthetic_payload.effective_at, datetime(2026, 4, 22, 15, 30, tzinfo=UTC).replace(second=0, microsecond=0))


if __name__ == "__main__":
    unittest.main()
