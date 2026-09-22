from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID

from app.jobs import (
    IngestPlayerStatsJobPayload,
    JobType,
    SyntheticTraderTickJobPayload,
    TopupJobPayload,
)
from app.scheduler import (
    DailyPlayerStatsIngestionPlan,
    InMemoryJobQueue,
    InMemoryScheduleClaimStore,
    SchedulerService,
)
from app.topups import TopupCadence


class SchedulerServiceTests(unittest.TestCase):
    def test_scheduled_jobs_are_created_as_correlated_runs(self) -> None:
        class RunRepository:
            def __init__(self) -> None:
                self.created = []

            def create_run(
                self,
                run_id,
                schedule_name,
                window_key,
                job_type,
                parameters,
                supersede_pending,
            ) -> bool:
                self.created.append(
                    (
                        run_id,
                        schedule_name,
                        window_key,
                        job_type,
                        parameters,
                        supersede_pending,
                    )
                )
                return True

            def mark_enqueue_failed(self, run_id, message) -> None:
                raise AssertionError("enqueue should not fail")

        queue = InMemoryJobQueue()
        runs = RunRepository()
        scheduler = SchedulerService(
            queue=queue,
            claim_store=InMemoryScheduleClaimStore(),
            plans=(DailyPlayerStatsIngestionPlan(),),
            run_repository=runs,
        )

        decisions = scheduler.schedule_due_jobs(
            datetime(2026, 4, 22, 15, 30, tzinfo=UTC)
        )

        self.assertEqual(len(runs.created), 1)
        self.assertEqual(runs.created[0][1], "daily-player-stats")
        self.assertEqual(runs.created[0][2], "2026-04-22")
        self.assertTrue(runs.created[0][5])
        self.assertIsInstance(queue.jobs[0].operation_run_id, UUID)
        self.assertEqual(decisions[0].job.operation_run_id, queue.jobs[0].operation_run_id)

    def test_existing_scheduled_run_is_not_enqueued_again(self) -> None:
        class ExistingRunRepository:
            def create_run(self, *args, **kwargs) -> bool:
                return False

            def mark_enqueue_failed(self, run_id, message) -> None:
                raise AssertionError("enqueue should not be attempted")

        queue = InMemoryJobQueue()
        scheduler = SchedulerService(
            queue=queue,
            claim_store=InMemoryScheduleClaimStore(),
            plans=(DailyPlayerStatsIngestionPlan(),),
            run_repository=ExistingRunRepository(),
        )

        decisions = scheduler.schedule_due_jobs(
            datetime(2026, 4, 22, 15, 30, tzinfo=UTC)
        )

        self.assertEqual(decisions, ())
        self.assertEqual(queue.jobs, [])

    def test_runtime_control_can_pause_an_enabled_schedule(self) -> None:
        class PausedControl:
            def is_enabled(self, schedule_name: str, default: bool) -> bool:
                return schedule_name != "synthetic-trader-ticks" and default

        queue = InMemoryJobQueue()
        scheduler = SchedulerService(
            queue=queue,
            claim_store=InMemoryScheduleClaimStore(),
            control_store=PausedControl(),
        )

        decisions = scheduler.schedule_due_jobs(
            datetime(2026, 4, 22, 15, 30, tzinfo=UTC)
        )

        self.assertNotIn("synthetic-trader-ticks", [item.schedule_name for item in decisions])
        self.assertEqual(len(decisions), 3)

    def test_schedule_due_jobs_enqueues_topup_jobs_once_per_window(self) -> None:
        queue = InMemoryJobQueue()
        claim_store = InMemoryScheduleClaimStore()
        scheduler = SchedulerService(queue=queue, claim_store=claim_store)
        effective_at = datetime(2026, 4, 22, 15, 30, tzinfo=UTC)

        first_run = scheduler.schedule_due_jobs(effective_at)
        second_run = scheduler.schedule_due_jobs(effective_at)

        self.assertEqual(len(first_run), 4)
        self.assertEqual(len(second_run), 0)
        self.assertEqual(len(queue.jobs), 4)

        weekly_payload = TopupJobPayload.from_payload(queue.jobs[0].payload)
        monthly_payload = TopupJobPayload.from_payload(queue.jobs[1].payload)
        synthetic_payload = SyntheticTraderTickJobPayload.from_payload(queue.jobs[2].payload)
        stats_payload = IngestPlayerStatsJobPayload.from_payload(queue.jobs[3].payload)
        self.assertEqual(weekly_payload.cadence, TopupCadence.WEEKLY)
        self.assertEqual(monthly_payload.cadence, TopupCadence.MONTHLY)
        self.assertEqual(queue.jobs[2].job_type, JobType.SYNTHETIC_TRADER_TICK)
        self.assertEqual(weekly_payload.effective_at, datetime(2026, 4, 20, 0, 0, tzinfo=UTC))
        self.assertEqual(monthly_payload.effective_at, datetime(2026, 4, 1, 0, 0, tzinfo=UTC))
        self.assertEqual(synthetic_payload.effective_at, datetime(2026, 4, 22, 15, 30, tzinfo=UTC).replace(second=0, microsecond=0))
        self.assertEqual(queue.jobs[3].job_type, JobType.INGEST_PLAYER_STATS)
        self.assertEqual(stats_payload.league, 9)
        self.assertEqual(stats_payload.season, 2025)

    def test_daily_player_stats_uses_configured_hour_as_window_boundary(self) -> None:
        queue = InMemoryJobQueue()
        scheduler = SchedulerService(
            queue=queue,
            claim_store=InMemoryScheduleClaimStore(),
            plans=(
                DailyPlayerStatsIngestionPlan(
                    league=9,
                    season=2025,
                    run_hour_utc=3,
                ),
            ),
        )

        before = scheduler.schedule_due_jobs(datetime(2026, 4, 22, 2, 59, tzinfo=UTC))
        after = scheduler.schedule_due_jobs(datetime(2026, 4, 22, 3, 0, tzinfo=UTC))
        duplicate = scheduler.schedule_due_jobs(datetime(2026, 4, 22, 18, 0, tzinfo=UTC))

        self.assertEqual(before[0].window_key, "2026-04-21")
        self.assertEqual(after[0].window_key, "2026-04-22")
        self.assertEqual(duplicate, ())
        self.assertEqual(len(queue.jobs), 2)

    def test_plan_provider_is_read_for_each_scheduler_cycle(self) -> None:
        hour = 3

        def plans():
            return (DailyPlayerStatsIngestionPlan(run_hour_utc=hour),)

        scheduler = SchedulerService(
            queue=InMemoryJobQueue(),
            claim_store=InMemoryScheduleClaimStore(),
            plan_provider=plans,
        )

        first = scheduler.schedule_due_jobs(datetime(2026, 4, 22, 2, 0, tzinfo=UTC))
        hour = 1
        second = scheduler.schedule_due_jobs(datetime(2026, 4, 22, 2, 1, tzinfo=UTC))

        self.assertEqual(first[0].window_key, "2026-04-21")
        self.assertEqual(second[0].window_key, "2026-04-22")


if __name__ == "__main__":
    unittest.main()
