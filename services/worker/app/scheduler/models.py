from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.jobs.models import TopupJobPayload, WorkerJob
from app.topups.models import TopupCadence, TopupWindow


@dataclass(frozen=True)
class RecurringTopupPlan:
    name: str
    cadence: TopupCadence
    enabled: bool = True

    def window_for(self, effective_at: datetime) -> TopupWindow:
        return TopupWindow.for_datetime(self.cadence, effective_at)

    def build_job(self, effective_at: datetime) -> WorkerJob:
        window = self.window_for(effective_at)
        return WorkerJob.topup(
            TopupJobPayload(
                cadence=self.cadence,
                effective_at=window.start,
            )
        )


@dataclass(frozen=True)
class ScheduledJobDecision:
    schedule_name: str
    cadence: TopupCadence
    window_key: str
    job: WorkerJob


def default_topup_plans() -> tuple[RecurringTopupPlan, ...]:
    return (
        RecurringTopupPlan(name="weekly-topups", cadence=TopupCadence.WEEKLY),
        RecurringTopupPlan(name="monthly-topups", cadence=TopupCadence.MONTHLY),
    )
