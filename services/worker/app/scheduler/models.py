from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.jobs.models import SyntheticTraderTickJobPayload, TopupJobPayload, WorkerJob
from app.jobs.models import JobType
from app.topups.models import TopupCadence, TopupWindow


class SchedulePlan(Protocol):
    name: str
    enabled: bool

    def window_key_for(self, effective_at: datetime) -> str: ...

    def build_job(self, effective_at: datetime) -> WorkerJob: ...


@dataclass(frozen=True)
class RecurringTopupPlan:
    name: str
    cadence: TopupCadence
    enabled: bool = True

    def window_for(self, effective_at: datetime) -> TopupWindow:
        return TopupWindow.for_datetime(self.cadence, effective_at)

    def window_key_for(self, effective_at: datetime) -> str:
        return self.window_for(effective_at).key

    def build_job(self, effective_at: datetime) -> WorkerJob:
        window = self.window_for(effective_at)
        return WorkerJob.topup(
            TopupJobPayload(
                cadence=self.cadence,
                effective_at=window.start,
            )
        )


@dataclass(frozen=True)
class SyntheticTraderTickPlan:
    name: str = "synthetic-trader-ticks"
    interval_minutes: int = 1
    enabled: bool = True

    def window_key_for(self, effective_at: datetime) -> str:
        return _normalize_tick_time(effective_at).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.synthetic_trader_tick(
            SyntheticTraderTickJobPayload(
                effective_at=_normalize_tick_time(effective_at),
            )
        )


@dataclass(frozen=True)
class ScheduledJobDecision:
    schedule_name: str
    job_type: JobType
    window_key: str
    job: WorkerJob


def default_scheduler_plans() -> tuple[SchedulePlan, ...]:
    return (
        RecurringTopupPlan(name="weekly-topups", cadence=TopupCadence.WEEKLY),
        RecurringTopupPlan(name="monthly-topups", cadence=TopupCadence.MONTHLY),
        SyntheticTraderTickPlan(),
    )


def _normalize_tick_time(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    normalized = normalized.astimezone(UTC)
    return normalized.replace(second=0, microsecond=0)
