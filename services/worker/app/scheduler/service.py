from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.jobs.models import WorkerJob
from app.scheduler.models import RecurringTopupPlan, ScheduledJobDecision, default_topup_plans


class JobQueue(Protocol):
    def enqueue(self, job: WorkerJob) -> None: ...


class ScheduleClaimStore(Protocol):
    def claim(self, schedule_name: str, window_key: str) -> bool: ...


class InMemoryJobQueue:
    def __init__(self) -> None:
        self.jobs: list[WorkerJob] = []

    def enqueue(self, job: WorkerJob) -> None:
        self.jobs.append(job)


class InMemoryScheduleClaimStore:
    def __init__(self) -> None:
        self._claims: set[tuple[str, str]] = set()

    def claim(self, schedule_name: str, window_key: str) -> bool:
        claim_key = (schedule_name, window_key)
        if claim_key in self._claims:
            return False
        self._claims.add(claim_key)
        return True


@dataclass(frozen=True)
class SchedulerService:
    queue: JobQueue
    claim_store: ScheduleClaimStore
    plans: tuple[RecurringTopupPlan, ...] = default_topup_plans()

    def schedule_due_jobs(self, effective_at: datetime) -> tuple[ScheduledJobDecision, ...]:
        decisions: list[ScheduledJobDecision] = []
        for plan in self.plans:
            if not plan.enabled:
                continue

            window = plan.window_for(effective_at)
            if not self.claim_store.claim(plan.name, window.key):
                continue

            job = plan.build_job(effective_at)
            self.queue.enqueue(job)
            decisions.append(
                ScheduledJobDecision(
                    schedule_name=plan.name,
                    cadence=plan.cadence,
                    window_key=window.key,
                    job=job,
                )
            )

        return tuple(decisions)
