from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.jobs.models import WorkerJob
from app.scheduler.models import SchedulePlan, ScheduledJobDecision, default_scheduler_plans


class JobQueue(Protocol):
    def enqueue(self, job: WorkerJob) -> None: ...


class ScheduleClaimStore(Protocol):
    def claim(self, schedule_name: str, window_key: str) -> bool: ...


class ScheduleControlStore(Protocol):
    def is_enabled(self, schedule_name: str, default: bool) -> bool: ...


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
    plans: tuple[SchedulePlan, ...] = default_scheduler_plans()
    control_store: ScheduleControlStore | None = None

    def schedule_due_jobs(self, effective_at: datetime) -> tuple[ScheduledJobDecision, ...]:
        decisions: list[ScheduledJobDecision] = []
        for plan in self.plans:
            enabled = (
                plan.enabled
                if self.control_store is None
                else self.control_store.is_enabled(plan.name, plan.enabled)
            )
            if not enabled:
                continue

            window_key = plan.window_key_for(effective_at)
            if not self.claim_store.claim(plan.name, window_key):
                continue

            job = plan.build_job(effective_at)
            self.queue.enqueue(job)
            decisions.append(
                ScheduledJobDecision(
                    schedule_name=plan.name,
                    job_type=job.job_type,
                    window_key=window_key,
                    job=job,
                )
            )

        return tuple(decisions)
