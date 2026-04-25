from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping

from app.topups.models import TopupCadence


class JobType(StrEnum):
    APPLY_TOPUPS = "APPLY_TOPUPS"
    SYNTHETIC_TRADER_TICK = "SYNTHETIC_TRADER_TICK"
    CHECK_MARKET_FREEZES = "CHECK_MARKET_FREEZES"
    INGEST_PLAYERS = "INGEST_PLAYERS"


@dataclass(frozen=True)
class TopupJobPayload:
    cadence: TopupCadence
    effective_at: datetime

    def to_payload(self) -> dict[str, str]:
        return {
            "cadence": self.cadence.value,
            "effective_at": _normalize_timestamp(self.effective_at).isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TopupJobPayload":
        return cls(
            cadence=TopupCadence(str(payload["cadence"])),
            effective_at=datetime.fromisoformat(str(payload["effective_at"])),
        )


@dataclass(frozen=True)
class WorkerJob:
    job_type: JobType
    payload: Mapping[str, Any]
    attempt: int = 0

    def to_message(self) -> dict[str, Any]:
        return {
            "job_type": self.job_type.value,
            "payload": dict(self.payload),
            "attempt": self.attempt,
        }

    @classmethod
    def from_message(cls, message: Mapping[str, Any]) -> "WorkerJob":
        payload = message.get("payload", {})
        if not isinstance(payload, Mapping):
            raise TypeError("worker job payload must be a mapping")
        return cls(
            job_type=JobType(str(message["job_type"])),
            payload=payload,
            attempt=int(message.get("attempt", 0)),
        )

    @classmethod
    def topup(cls, payload: TopupJobPayload) -> "WorkerJob":
        return cls(job_type=JobType.APPLY_TOPUPS, payload=payload.to_payload())

    def with_attempt(self, attempt: int) -> "WorkerJob":
        return WorkerJob(job_type=self.job_type, payload=self.payload, attempt=attempt)


@dataclass(frozen=True)
class JobExecutionResult:
    job_type: JobType
    handled_at: datetime
    successful_items: int
    skipped_items: int
    failed_items: int
    retryable_failures: int = 0


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
