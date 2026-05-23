from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from app.jobs import (
    JobType,
    RetryableJobError,
    SyntheticTraderTickJobHandler,
    SyntheticTraderTickJobPayload,
    TopupJobHandler,
    TopupJobPayload,
    WorkerJob,
    WorkerJobRunner,
)
from app.synthetic_traders import SyntheticTraderTickBatchResult, SyntheticTraderTickOutcome, TickOutcomeStatus
from app.topups import TopupBatchResult, TopupCadence, TopupDispatchOutcome, TopupOutcomeStatus, TopupWindow


class FakeTopupService:
    def __init__(self, result: TopupBatchResult) -> None:
        self.result = result
        self.calls: list[tuple[TopupCadence, datetime]] = []

    def apply_topups(self, cadence: TopupCadence, effective_at: datetime) -> TopupBatchResult:
        self.calls.append((cadence, effective_at))
        return self.result


class FakeSyntheticTraderService:
    def __init__(self, result: SyntheticTraderTickBatchResult) -> None:
        self.result = result
        self.calls: list[datetime] = []

    def tick_due_bots(self, effective_at: datetime) -> SyntheticTraderTickBatchResult:
        self.calls.append(effective_at)
        return self.result


class JobHandlerTests(unittest.TestCase):
    def test_topup_job_handler_returns_job_counts(self) -> None:
        service = FakeTopupService(
            TopupBatchResult(
                cadence=TopupCadence.WEEKLY,
                window=TopupWindow.for_datetime(
                    TopupCadence.WEEKLY, datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
                ),
                outcomes=(
                    TopupDispatchOutcome(
                        request_id="req_1",
                        account_id=uuid4(),
                        portfolio_id=uuid4(),
                        cadence=TopupCadence.WEEKLY,
                        amount="250.0000",
                        status=TopupOutcomeStatus.APPLIED,
                        window_key="2026-04-20",
                    ),
                ),
            )
        )
        handler = TopupJobHandler(
            topup_service=service,
            clock=lambda: datetime(2026, 4, 22, 12, 5, tzinfo=UTC),
        )
        runner = WorkerJobRunner({JobType.APPLY_TOPUPS: handler})

        result = runner.run(
            WorkerJob.topup(
                TopupJobPayload(
                    cadence=TopupCadence.WEEKLY,
                    effective_at=datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
                )
            )
        )

        self.assertEqual(result.successful_items, 1)
        self.assertEqual(result.failed_items, 0)
        self.assertEqual(service.calls[0][0], TopupCadence.WEEKLY)

    def test_topup_job_handler_raises_for_retryable_failures(self) -> None:
        service = FakeTopupService(
            TopupBatchResult(
                cadence=TopupCadence.WEEKLY,
                window=TopupWindow.for_datetime(
                    TopupCadence.WEEKLY, datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
                ),
                outcomes=(
                    TopupDispatchOutcome(
                        request_id="req_1",
                        account_id=uuid4(),
                        portfolio_id=uuid4(),
                        cadence=TopupCadence.WEEKLY,
                        amount="250.0000",
                        status=TopupOutcomeStatus.FAILED,
                        window_key="2026-04-20",
                        retryable=True,
                        message="temporary outage",
                    ),
                ),
            )
        )
        handler = TopupJobHandler(topup_service=service)

        with self.assertRaises(RetryableJobError) as context:
            handler.handle(
                WorkerJob.topup(
                    TopupJobPayload(
                        cadence=TopupCadence.WEEKLY,
                        effective_at=datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
                    )
                )
            )

        self.assertEqual(context.exception.result.retryable_failures, 1)

    def test_synthetic_trader_job_handler_reports_submission_counts(self) -> None:
        service = FakeSyntheticTraderService(
            SyntheticTraderTickBatchResult(
                processed_bots=1,
                outcomes=(
                    SyntheticTraderTickOutcome(
                        bot_id=uuid4(),
                        account_id=uuid4(),
                        portfolio_id=uuid4(),
                        status=TickOutcomeStatus.SUBMITTED,
                    ),
                    SyntheticTraderTickOutcome(
                        bot_id=uuid4(),
                        account_id=uuid4(),
                        portfolio_id=uuid4(),
                        status=TickOutcomeStatus.SKIPPED,
                    ),
                ),
            )
        )
        handler = SyntheticTraderTickJobHandler(
            synthetic_trader_service=service,
            clock=lambda: datetime(2026, 4, 22, 12, 5, tzinfo=UTC),
        )

        result = handler.handle(
            WorkerJob.synthetic_trader_tick(
                SyntheticTraderTickJobPayload(
                    effective_at=datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
                )
            )
        )

        self.assertEqual(result.job_type, JobType.SYNTHETIC_TRADER_TICK)
        self.assertEqual(result.successful_items, 1)
        self.assertEqual(result.skipped_items, 1)
        self.assertEqual(service.calls[0], datetime(2026, 4, 22, 12, 0, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
