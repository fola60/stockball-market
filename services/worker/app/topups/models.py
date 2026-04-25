from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class TopupCadence(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


@dataclass(frozen=True)
class TopupWindow:
    cadence: TopupCadence
    start: datetime
    end_exclusive: datetime

    @property
    def key(self) -> str:
        return self.start.date().isoformat()

    @classmethod
    def for_datetime(cls, cadence: TopupCadence, effective_at: datetime) -> "TopupWindow":
        normalized = _normalize_timestamp(effective_at)
        if cadence is TopupCadence.WEEKLY:
            start = normalized - timedelta(days=normalized.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            return cls(cadence=cadence, start=start, end_exclusive=start + timedelta(days=7))

        start = normalized.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end_exclusive = start.replace(year=start.year + 1, month=1)
        else:
            end_exclusive = start.replace(month=start.month + 1)
        return cls(cadence=cadence, start=start, end_exclusive=end_exclusive)


@dataclass(frozen=True)
class TopupPolicy:
    account_id: UUID
    portfolio_id: UUID
    cadence: TopupCadence
    amount: str
    enabled: bool = True


class TopupRecordStatus(StrEnum):
    PLANNED = "PLANNED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class TopupOutcomeStatus(StrEnum):
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class TopupAuditRecord:
    request_id: str
    account_id: UUID
    portfolio_id: UUID
    cadence: TopupCadence
    amount: str
    window_start: datetime
    window_end_exclusive: datetime
    status: TopupRecordStatus
    created_at: datetime
    updated_at: datetime
    ledger_entry_id: UUID | None = None
    applied_at: datetime | None = None
    retryable: bool = False
    failure_code: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class TopupDispatchOutcome:
    request_id: str
    account_id: UUID
    portfolio_id: UUID
    cadence: TopupCadence
    amount: str
    status: TopupOutcomeStatus
    window_key: str
    ledger_entry_id: UUID | None = None
    retryable: bool = False
    message: str | None = None


@dataclass(frozen=True)
class TopupBatchResult:
    cadence: TopupCadence
    window: TopupWindow
    outcomes: tuple[TopupDispatchOutcome, ...]

    @property
    def applied_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is TopupOutcomeStatus.APPLIED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is TopupOutcomeStatus.SKIPPED)

    @property
    def failed_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is TopupOutcomeStatus.FAILED)

    @property
    def retryable_failure_count(self) -> int:
        return sum(
            1
            for outcome in self.outcomes
            if outcome.status is TopupOutcomeStatus.FAILED and outcome.retryable
        )

    @property
    def has_retryable_failures(self) -> bool:
        return self.retryable_failure_count > 0


class TopupPolicyStore(Protocol):
    def list_policies(self, cadence: TopupCadence) -> list[TopupPolicy]: ...


class TopupAuditStore(Protocol):
    def get_record(self, request_id: str) -> TopupAuditRecord | None: ...

    def save_record(self, record: TopupAuditRecord) -> None: ...


class InMemoryTopupPolicyStore:
    def __init__(self, policies: list[TopupPolicy]) -> None:
        self._policies = list(policies)

    def list_policies(self, cadence: TopupCadence) -> list[TopupPolicy]:
        return [policy for policy in self._policies if policy.cadence is cadence]


class InMemoryTopupAuditStore:
    def __init__(self) -> None:
        self._records: dict[str, TopupAuditRecord] = {}

    def get_record(self, request_id: str) -> TopupAuditRecord | None:
        return self._records.get(request_id)

    def save_record(self, record: TopupAuditRecord) -> None:
        self._records[record.request_id] = record


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
