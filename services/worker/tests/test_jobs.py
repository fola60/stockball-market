from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from app.jobs import (
    IngestSocialFeedsJobHandler,
    IngestSocialFeedsJobPayload,
    JobExecutionResult,
    JobType,
    RetryableJobError,
    SyntheticTraderTickJobHandler,
    SyntheticTraderTickJobPayload,
    TopupJobHandler,
    TopupJobPayload,
    WorkerJob,
    WorkerJobRunner,
)
from app.synthetic_traders import (
    StrategyEngine,
    SyntheticTraderTickBatchResult,
    SyntheticTraderTickDiagnostics,
    SyntheticTraderTickOutcome,
    TickOutcomeStatus,
)
from app.topups import (
    TopupBatchResult,
    TopupCadence,
    TopupDispatchOutcome,
    TopupOutcomeStatus,
    TopupWindow,
)


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
        self.calls: list[tuple[datetime, dict[str, object]]] = []

    def tick_due_bots(self, effective_at: datetime, **kwargs) -> SyntheticTraderTickBatchResult:
        self.calls.append((effective_at, kwargs))
        return self.result


class FakeSyntheticTopupPolicyProvisioner:
    def __init__(self) -> None:
        self.calls = []

    def ensure_active_synthetic_trader_policies(self, cadence, amount):
        self.calls.append((cadence, amount))
        return 100


class JobHandlerTests(unittest.TestCase):
    def test_social_feed_batch_aggregates_due_source_results(self) -> None:
        subscription_ids = [uuid4(), uuid4()]

        class Repository:
            call = None

            def list_due_subscriptions(self, as_of, *, limit, provider):
                self.call = (as_of, limit, provider)
                return subscription_ids

        class SourceHandler:
            def handle(self, job):
                return JobExecutionResult(
                    job_type=job.job_type,
                    handled_at=datetime(2026, 9, 12, tzinfo=UTC),
                    successful_items=1,
                    skipped_items=4,
                    failed_items=0,
                    metrics={
                        "fetched_documents": 5,
                        "immediate_articles_enriched": 1,
                        "immediate_documents_processed": 1,
                    },
                )

        repository = Repository()
        handler = IngestSocialFeedsJobHandler(
            repository=repository,  # type: ignore[arg-type]
            source_handler=SourceHandler(),  # type: ignore[arg-type]
            clock=lambda: datetime(2026, 9, 12, tzinfo=UTC),
        )

        result = handler.handle(
            WorkerJob.ingest_social_feeds(
                IngestSocialFeedsJobPayload(provider="RSS", limit=50)
            )
        )

        self.assertEqual(result.successful_items, 2)
        self.assertEqual(result.skipped_items, 8)
        self.assertEqual(result.metrics["subscriptions_polled"], 2)
        self.assertEqual(result.metrics["articles_enriched"], 2)
        self.assertEqual(repository.call[1:], (50, "RSS"))

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

    def test_topup_job_handler_configures_synthetic_policies_and_reports_cash(self) -> None:
        service = FakeTopupService(
            TopupBatchResult(
                cadence=TopupCadence.WEEKLY,
                window=TopupWindow.for_datetime(
                    TopupCadence.WEEKLY, datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
                ),
                outcomes=tuple(
                    TopupDispatchOutcome(
                        request_id=f"req_{index}",
                        account_id=uuid4(),
                        portfolio_id=uuid4(),
                        cadence=TopupCadence.WEEKLY,
                        amount="100000.0000",
                        status=TopupOutcomeStatus.APPLIED,
                        window_key="2026-04-20",
                    )
                    for index in range(2)
                ),
            )
        )
        provisioner = FakeSyntheticTopupPolicyProvisioner()
        handler = TopupJobHandler(
            topup_service=service,
            synthetic_policy_provisioner=provisioner,
        )

        result = handler.handle(
            WorkerJob.topup(
                TopupJobPayload(
                    cadence=TopupCadence.WEEKLY,
                    effective_at=datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
                    synthetic_trader_amount="100000.0000",
                )
            )
        )

        self.assertEqual(provisioner.calls, [(TopupCadence.WEEKLY, "100000.0000")])
        self.assertEqual(result.successful_items, 2)
        self.assertEqual(result.metrics["configured_policies"], 100)
        self.assertEqual(result.metrics["credited_amount"], "200000.0000")

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
        bot_id = uuid4()
        service = FakeSyntheticTraderService(
            SyntheticTraderTickBatchResult(
                processed_bots=1,
                outcomes=(
                    SyntheticTraderTickOutcome(
                        bot_id=bot_id,
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
                    SyntheticTraderTickOutcome(
                        bot_id=uuid4(),
                        account_id=uuid4(),
                        portfolio_id=uuid4(),
                        instrument_id=uuid4(),
                        status=TickOutcomeStatus.FAILED,
                        request_id="failed-request",
                        error_code="invalid_resulting_price",
                        message="order would result in an invalid instrument price.",
                        error_details={"new_price": "-1.0000"},
                    ),
                ),
                diagnostics=(
                    SyntheticTraderTickDiagnostics(
                        bot_id=bot_id,
                        strategy_engine=StrategyEngine.NOISE,
                        candidates_loaded=10,
                        candidates_evaluated=8,
                        candidate_exclusions={"position_not_included": 2},
                        decisions={"BUY": 1, "HOLD": 7},
                        negative_alpha={"below_zero_above_sell_threshold": 3},
                        rejection_reasons={"cash_reserve": 1},
                        recovery_decisions=1,
                        recovery_orders=1,
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
        self.assertEqual(result.failed_items, 1)
        self.assertEqual(service.calls[0][0], datetime(2026, 4, 22, 12, 0, tzinfo=UTC))
        self.assertEqual(service.calls[0][1]["limit"], 100)
        self.assertFalse(service.calls[0][1]["force_timing"])
        diagnostics = result.metrics["decision_diagnostics"]
        self.assertEqual(diagnostics["candidates_loaded"], 10)
        self.assertEqual(diagnostics["rejection_reasons"], {"cash_reserve": 1})
        self.assertEqual(diagnostics["by_strategy"]["NOISE"]["recovery_decisions"], 1)
        self.assertEqual(diagnostics["by_strategy"]["NOISE"]["recovery_orders"], 1)
        self.assertEqual(
            result.metrics["execution_failures"], {"invalid_resulting_price": 1}
        )
        self.assertEqual(
            result.metrics["failed_order_samples"][0]["request_id"],
            "failed-request",
        )

    def test_synthetic_trader_job_handler_forces_selected_bots(self) -> None:
        bot_ids = (uuid4(), uuid4())
        service = FakeSyntheticTraderService(
            SyntheticTraderTickBatchResult(
                processed_bots=2,
                outcomes=(
                    SyntheticTraderTickOutcome(
                        bot_id=bot_ids[0],
                        account_id=uuid4(),
                        portfolio_id=uuid4(),
                        status=TickOutcomeStatus.SUBMITTED,
                    ),
                    SyntheticTraderTickOutcome(
                        bot_id=bot_ids[1],
                        account_id=uuid4(),
                        portfolio_id=uuid4(),
                        status=TickOutcomeStatus.SKIPPED,
                    ),
                ),
            )
        )
        handler = SyntheticTraderTickJobHandler(synthetic_trader_service=service)

        result = handler.handle(
            WorkerJob.synthetic_trader_tick(
                SyntheticTraderTickJobPayload(
                    effective_at=datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
                    force_timing=True,
                    bot_ids=bot_ids,
                    tick_count=3,
                )
            )
        )

        self.assertEqual(service.calls[0][1]["limit"], 500)
        self.assertTrue(service.calls[0][1]["force_timing"])
        self.assertEqual(service.calls[0][1]["bot_ids"], bot_ids)
        self.assertEqual(len(service.calls), 3)
        self.assertGreater(service.calls[1][0], service.calls[0][0])
        self.assertTrue(result.metrics["forced"])
        self.assertEqual(result.metrics["targeted_bots"], 2)
        self.assertEqual(result.metrics["processed_bots"], 6)
        self.assertEqual(result.metrics["ticks_requested"], 3)
        self.assertEqual(result.metrics["ticks_completed"], 3)
        self.assertEqual(result.successful_items, 3)
        self.assertEqual(result.skipped_items, 3)


if __name__ == "__main__":
    unittest.main()
