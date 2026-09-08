from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

from app.jobs.models import JobType, WorkerJob
from app.scheduler.models import ScheduledJobDecision, SchedulePlan, default_scheduler_plans


class JobQueue(Protocol):
    def enqueue(self, job: WorkerJob) -> None: ...


class ScheduleClaimStore(Protocol):
    def claim(self, schedule_name: str, window_key: str) -> bool: ...


class ScheduleControlStore(Protocol):
    def is_enabled(self, schedule_name: str, default: bool) -> bool: ...


class ScheduledRunRepository(Protocol):
    def create_run(
        self,
        run_id: UUID,
        schedule_name: str,
        window_key: str,
        job_type: JobType,
        parameters: Mapping[str, Any],
        supersede_pending: bool,
    ) -> bool: ...

    def mark_enqueue_failed(self, run_id: UUID, message: str) -> None: ...


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
    run_repository: ScheduledRunRepository | None = None

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
            if self.run_repository is not None:
                run_id = uuid4()
                created = self.run_repository.create_run(
                    run_id,
                    plan.name,
                    window_key,
                    job.job_type,
                    job.payload,
                    plan.supersede_pending,
                )
                if not created:
                    continue
                job = job.with_operation_run_id(run_id)
            try:
                self.queue.enqueue(job)
            except Exception as error:
                if self.run_repository is not None and job.operation_run_id is not None:
                    self.run_repository.mark_enqueue_failed(
                        job.operation_run_id, f"failed to enqueue scheduled job: {error}"
                    )
                raise
            decisions.append(
                ScheduledJobDecision(
                    schedule_name=plan.name,
                    job_type=job.job_type,
                    window_key=window_key,
                    job=job,
                )
            )

        return tuple(decisions)
