from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from app.clients.trading_engine import (
    ApplyTopupCommand,
    LedgerReason,
    TradingEngineClient,
    TradingEngineClientError,
    TradingEngineUnavailableError,
)
from app.topups.models import (
    TopupAuditRecord,
    TopupAuditStore,
    TopupBatchResult,
    TopupCadence,
    TopupDispatchOutcome,
    TopupOutcomeStatus,
    TopupPolicy,
    TopupPolicyStore,
    TopupRecordStatus,
    TopupWindow,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class TopupService:
    trading_engine_client: TradingEngineClient
    policy_store: TopupPolicyStore
    audit_store: TopupAuditStore
    clock: Callable[[], datetime] = _utc_now

    def apply_topups(self, cadence: TopupCadence, effective_at: datetime) -> TopupBatchResult:
        window = TopupWindow.for_datetime(cadence, effective_at)
        outcomes: list[TopupDispatchOutcome] = []

        for policy in self.policy_store.list_policies(cadence):
            if not policy.enabled:
                continue

            request_id = self.build_request_id(policy, window)
            existing = self.audit_store.get_record(request_id)
            if existing is not None and existing.status is TopupRecordStatus.APPLIED:
                outcomes.append(
                    TopupDispatchOutcome(
                        request_id=request_id,
                        account_id=policy.account_id,
                        portfolio_id=policy.portfolio_id,
                        cadence=policy.cadence,
                        amount=policy.amount,
                        status=TopupOutcomeStatus.SKIPPED,
                        window_key=window.key,
                        ledger_entry_id=existing.ledger_entry_id,
                        message="top-up already applied for the current cadence window",
                    )
                )
                continue

            self.audit_store.save_record(self._build_planned_record(policy, request_id, window))

            try:
                ledger_entry = self.trading_engine_client.apply_topup(
                    ApplyTopupCommand(
                        request_id=request_id,
                        account_id=policy.account_id,
                        portfolio_id=policy.portfolio_id,
                        amount=policy.amount,
                        reason=_ledger_reason_for(cadence),
                    )
                )
            except TradingEngineUnavailableError as exc:
                outcomes.append(
                    self._record_failure(
                        policy=policy,
                        request_id=request_id,
                        window=window,
                        retryable=True,
                        failure_code="trading_engine_unavailable",
                        failure_message=str(exc),
                    )
                )
                continue
            except TradingEngineClientError as exc:
                outcomes.append(
                    self._record_failure(
                        policy=policy,
                        request_id=request_id,
                        window=window,
                        retryable=exc.retryable,
                        failure_code=str(exc.body.get("code", "trading_engine_error")),
                        failure_message=str(
                            exc.body.get("message", "trading engine request failed")
                        ),
                    )
                )
                continue

            now = self.clock()
            self.audit_store.save_record(
                TopupAuditRecord(
                    request_id=request_id,
                    account_id=policy.account_id,
                    portfolio_id=policy.portfolio_id,
                    cadence=policy.cadence,
                    amount=policy.amount,
                    window_start=window.start,
                    window_end_exclusive=window.end_exclusive,
                    status=TopupRecordStatus.APPLIED,
                    created_at=_created_at_for(existing, now),
                    updated_at=now,
                    ledger_entry_id=ledger_entry.id,
                    applied_at=ledger_entry.created_at,
                )
            )
            outcomes.append(
                TopupDispatchOutcome(
                    request_id=request_id,
                    account_id=policy.account_id,
                    portfolio_id=policy.portfolio_id,
                    cadence=policy.cadence,
                    amount=policy.amount,
                    status=TopupOutcomeStatus.APPLIED,
                    window_key=window.key,
                    ledger_entry_id=ledger_entry.id,
                )
            )

        return TopupBatchResult(cadence=cadence, window=window, outcomes=tuple(outcomes))

    def build_request_id(self, policy: TopupPolicy, window: TopupWindow) -> str:
        return (
            f"topup:{policy.cadence.value.lower()}:{window.key}:"
            f"{policy.account_id}:{policy.portfolio_id}"
        )

    def _build_planned_record(
        self,
        policy: TopupPolicy,
        request_id: str,
        window: TopupWindow,
    ) -> TopupAuditRecord:
        now = self.clock()
        existing = self.audit_store.get_record(request_id)
        return TopupAuditRecord(
            request_id=request_id,
            account_id=policy.account_id,
            portfolio_id=policy.portfolio_id,
            cadence=policy.cadence,
            amount=policy.amount,
            window_start=window.start,
            window_end_exclusive=window.end_exclusive,
            status=TopupRecordStatus.PLANNED,
            created_at=_created_at_for(existing, now),
            updated_at=now,
        )

    def _record_failure(
        self,
        policy: TopupPolicy,
        request_id: str,
        window: TopupWindow,
        retryable: bool,
        failure_code: str,
        failure_message: str,
    ) -> TopupDispatchOutcome:
        now = self.clock()
        existing = self.audit_store.get_record(request_id)
        self.audit_store.save_record(
            TopupAuditRecord(
                request_id=request_id,
                account_id=policy.account_id,
                portfolio_id=policy.portfolio_id,
                cadence=policy.cadence,
                amount=policy.amount,
                window_start=window.start,
                window_end_exclusive=window.end_exclusive,
                status=TopupRecordStatus.FAILED,
                created_at=_created_at_for(existing, now),
                updated_at=now,
                retryable=retryable,
                failure_code=failure_code,
                failure_message=failure_message,
            )
        )
        return TopupDispatchOutcome(
            request_id=request_id,
            account_id=policy.account_id,
            portfolio_id=policy.portfolio_id,
            cadence=policy.cadence,
            amount=policy.amount,
            status=TopupOutcomeStatus.FAILED,
            window_key=window.key,
            retryable=retryable,
            message=failure_message,
        )


def _ledger_reason_for(cadence: TopupCadence) -> LedgerReason:
    if cadence is TopupCadence.WEEKLY:
        return LedgerReason.WEEKLY_TOPUP
    return LedgerReason.MONTHLY_TOPUP


def _created_at_for(existing: TopupAuditRecord | None, default: datetime) -> datetime:
    if existing is None:
        return default
    return existing.created_at
