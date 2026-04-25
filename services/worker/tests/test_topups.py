from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.clients.trading_engine import (
    ApplyTopupCommand,
    CashLedgerEntryRecord,
    LedgerReason,
    TradingEngineClientError,
)
from app.topups import (
    InMemoryTopupAuditStore,
    InMemoryTopupPolicyStore,
    TopupCadence,
    TopupOutcomeStatus,
    TopupPolicy,
    TopupRecordStatus,
    TopupService,
    TopupWindow,
)


class FakeTradingEngineClient:
    def __init__(self) -> None:
        self.commands: list[ApplyTopupCommand] = []
        self.failures: dict[str, Exception] = {}

    def apply_topup(self, command: ApplyTopupCommand) -> CashLedgerEntryRecord:
        self.commands.append(command)
        failure = self.failures.get(command.request_id)
        if failure is not None:
            raise failure
        return CashLedgerEntryRecord(
            id=uuid4(),
            account_id=command.account_id,
            portfolio_id=command.portfolio_id,
            trade_id=None,
            reason=command.reason,
            amount_delta=command.amount,
            balance_after="10250.0000",
            source_request_id=command.request_id,
            created_at=datetime(2026, 4, 22, 9, 0, tzinfo=UTC),
        )


class TopupServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.account_id = uuid4()
        self.portfolio_id = uuid4()
        self.policy_store = InMemoryTopupPolicyStore(
            [
                TopupPolicy(
                    account_id=self.account_id,
                    portfolio_id=self.portfolio_id,
                    cadence=TopupCadence.WEEKLY,
                    amount="250.0000",
                ),
                TopupPolicy(
                    account_id=uuid4(),
                    portfolio_id=uuid4(),
                    cadence=TopupCadence.MONTHLY,
                    amount="1000.0000",
                ),
            ]
        )
        self.audit_store = InMemoryTopupAuditStore()
        self.client = FakeTradingEngineClient()
        self.service = TopupService(
            trading_engine_client=self.client,
            policy_store=self.policy_store,
            audit_store=self.audit_store,
            clock=lambda: datetime(2026, 4, 22, 8, 0, tzinfo=UTC),
        )

    def test_apply_topups_uses_deterministic_request_ids(self) -> None:
        effective_at = datetime(2026, 4, 22, 13, 30, tzinfo=UTC)

        result = self.service.apply_topups(TopupCadence.WEEKLY, effective_at)

        self.assertEqual(result.applied_count, 1)
        self.assertEqual(result.skipped_count, 0)
        self.assertEqual(len(self.client.commands), 1)
        self.assertEqual(
            self.client.commands[0].request_id,
            f"topup:weekly:2026-04-20:{self.account_id}:{self.portfolio_id}",
        )
        self.assertEqual(self.client.commands[0].reason, LedgerReason.WEEKLY_TOPUP)

    def test_apply_topups_skips_already_applied_window(self) -> None:
        effective_at = datetime(2026, 4, 22, 13, 30, tzinfo=UTC)
        window = TopupWindow.for_datetime(TopupCadence.WEEKLY, effective_at)
        request_id = self.service.build_request_id(self.policy_store.list_policies(TopupCadence.WEEKLY)[0], window)
        self.audit_store.save_record(
            self._applied_record(request_id=request_id, ledger_entry_id=uuid4(), window=window)
        )

        result = self.service.apply_topups(TopupCadence.WEEKLY, effective_at)

        self.assertEqual(result.applied_count, 0)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(result.outcomes[0].status, TopupOutcomeStatus.SKIPPED)
        self.assertEqual(len(self.client.commands), 0)

    def test_apply_topups_marks_retryability_from_client_errors(self) -> None:
        effective_at = datetime(2026, 4, 22, 13, 30, tzinfo=UTC)
        window = TopupWindow.for_datetime(TopupCadence.WEEKLY, effective_at)
        policy = self.policy_store.list_policies(TopupCadence.WEEKLY)[0]
        request_id = self.service.build_request_id(policy, window)
        self.client.failures[request_id] = TradingEngineClientError(
            503,
            {
                "code": "trading_engine_unavailable",
                "message": "temporary outage",
            },
        )

        result = self.service.apply_topups(TopupCadence.WEEKLY, effective_at)

        self.assertEqual(result.failed_count, 1)
        self.assertTrue(result.has_retryable_failures)
        self.assertTrue(result.outcomes[0].retryable)
        record = self.audit_store.get_record(request_id)
        assert record is not None
        self.assertEqual(record.status, TopupRecordStatus.FAILED)
        self.assertTrue(record.retryable)

    def _applied_record(
        self,
        request_id: str,
        ledger_entry_id: UUID,
        window: TopupWindow,
    ):
        from app.topups.models import TopupAuditRecord

        return TopupAuditRecord(
            request_id=request_id,
            account_id=self.account_id,
            portfolio_id=self.portfolio_id,
            cadence=TopupCadence.WEEKLY,
            amount="250.0000",
            window_start=window.start,
            window_end_exclusive=window.end_exclusive,
            status=TopupRecordStatus.APPLIED,
            created_at=datetime(2026, 4, 22, 8, 0, tzinfo=UTC),
            updated_at=datetime(2026, 4, 22, 8, 0, tzinfo=UTC),
            ledger_entry_id=ledger_entry_id,
            applied_at=datetime(2026, 4, 22, 8, 0, tzinfo=UTC),
        )


if __name__ == "__main__":
    unittest.main()
