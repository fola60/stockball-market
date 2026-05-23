from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.scheduler import InMemoryJobQueue, InMemoryScheduleClaimStore, SchedulerProcess, SchedulerService


class SchedulerProcessTests(unittest.TestCase):
    def test_run_once_returns_enqueued_job_count(self) -> None:
        scheduler = SchedulerService(
            queue=InMemoryJobQueue(),
            claim_store=InMemoryScheduleClaimStore(),
        )
        process = SchedulerProcess(
            scheduler=scheduler,
            clock=lambda: datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
        )

        count = process.run_once()

        self.assertEqual(count, 3)


if __name__ == "__main__":
    unittest.main()
