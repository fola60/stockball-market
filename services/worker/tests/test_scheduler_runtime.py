from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.scheduler import (
    InMemoryJobQueue,
    InMemoryScheduleClaimStore,
    SchedulerProcess,
    SchedulerService,
)


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

        self.assertEqual(count, 5)

    def test_run_once_records_scheduler_heartbeat(self) -> None:
        class Reporter:
            event = None

            def record_scheduler_heartbeat(self, checked_at, scheduled_names):
                self.event = (checked_at, scheduled_names)

        reporter = Reporter()
        checked_at = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
        process = SchedulerProcess(
            scheduler=SchedulerService(
                queue=InMemoryJobQueue(),
                claim_store=InMemoryScheduleClaimStore(),
            ),
            clock=lambda: checked_at,
            status_reporter=reporter,
        )

        process.run_once()

        self.assertEqual(reporter.event[0], checked_at)
        self.assertEqual(len(reporter.event[1]), 5)

    def test_run_once_performs_housekeeping_before_scheduling(self) -> None:
        events = []
        checked_at = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)

        class Queue(InMemoryJobQueue):
            def enqueue(self, job):
                events.append("enqueue")
                super().enqueue(job)

        process = SchedulerProcess(
            scheduler=SchedulerService(
                queue=Queue(),
                claim_store=InMemoryScheduleClaimStore(),
            ),
            clock=lambda: checked_at,
            housekeeping=lambda as_of: events.append(("housekeeping", as_of)),
        )

        process.run_once()

        self.assertEqual(events[0], ("housekeeping", checked_at))
        self.assertIn("enqueue", events[1:])


if __name__ == "__main__":
    unittest.main()
