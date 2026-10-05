"""Hand one-off bootstrap work to the long-running worker and wait for it to finish.

The development-market bootstrap runs in a fresh, short-lived container. FBref's browser
fallback reliably succeeds from the long-running ingestion worker but is challenged from a
fresh container, so FBref ingestion is queued onto the worker instead of run in-process.
Each job is recorded as a MANUAL `job_runs` row, exactly as an admin-triggered run is, so it
shows up in the admin UI and the worker reports its outcome there.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID, uuid4

from app.database import connection as pooled_connection
from app.jobs.models import WorkerJob

TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "SUPERSEDED"})


class WorkerJobFailedError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobRunStatus:
    run_id: UUID
    status: str
    successful_items: int = 0
    skipped_items: int = 0
    failed_items: int = 0
    error_message: str | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)


class JobRunStore(Protocol):
    def create_manual_run(
        self,
        run_id: UUID,
        operation_type: str,
        job_type: str,
        parameters: Mapping[str, Any],
    ) -> None: ...

    def mark_enqueue_failed(self, run_id: UUID, message: str) -> None: ...

    def get_status(self, run_id: UUID) -> JobRunStatus | None: ...


class JobQueue(Protocol):
    def enqueue(self, job: WorkerJob) -> None: ...


class WorkerJobDispatcher:
    def __init__(
        self,
        store: JobRunStore,
        queue: JobQueue,
        *,
        poll_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store = store
        self._queue = queue
        self._poll_seconds = poll_seconds
        self._clock = clock
        self._sleep = sleep

    def run(self, operation_type: str, job: WorkerJob, timeout: timedelta) -> JobRunStatus:
        """Queue `job`, wait for the worker to finish it, and return its final status.

        Raises WorkerJobFailedError unless the run succeeds within `timeout`.
        """
        run_id = uuid4()
        self._store.create_manual_run(run_id, operation_type, job.job_type.value, job.payload)
        try:
            self._queue.enqueue(job.with_operation_run_id(run_id))
        except Exception as error:
            self._store.mark_enqueue_failed(run_id, f"failed to enqueue operation: {error}")
            raise

        deadline = self._clock() + timeout.total_seconds()
        while True:
            status = self._store.get_status(run_id)
            if status is not None and status.status in TERMINAL_STATUSES:
                if status.status != "SUCCEEDED":
                    raise WorkerJobFailedError(
                        f"{operation_type} run {run_id} ended {status.status}: "
                        f"{status.error_message or 'no error message'}"
                    )
                return status
            if self._clock() >= deadline:
                current = status.status if status is not None else "missing"
                raise WorkerJobFailedError(
                    f"{operation_type} run {run_id} did not finish within "
                    f"{int(timeout.total_seconds())}s (status {current}); "
                    "is the ingestion worker running?"
                )
            self._sleep(self._poll_seconds)


class PostgresJobRunStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def create_manual_run(
        self,
        run_id: UUID,
        operation_type: str,
        job_type: str,
        parameters: Mapping[str, Any],
    ) -> None:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO job_runs (id, operation_type, job_type, source, status, parameters)
                    VALUES (
                        %(id)s, %(operation_type)s, %(job_type)s, 'MANUAL', 'QUEUED',
                        %(parameters)s::jsonb
                    )
                    """,
                    {
                        "id": str(run_id),
                        "operation_type": operation_type,
                        "job_type": job_type,
                        "parameters": json.dumps(dict(parameters), default=str),
                    },
                )

    def mark_enqueue_failed(self, run_id: UUID, message: str) -> None:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE job_runs
                    SET status = 'FAILED', error_message = %(message)s,
                        failed_items = 1, completed_at = now(), updated_at = now()
                    WHERE id = %(id)s
                    """,
                    {"id": str(run_id), "message": message[:2000]},
                )

    def get_status(self, run_id: UUID) -> JobRunStatus | None:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, successful_items, skipped_items, failed_items,
                           error_message, metrics
                    FROM job_runs
                    WHERE id = %(id)s
                    """,
                    {"id": str(run_id)},
                )
                row = cursor.fetchone()
        if row is None:
            return None
        status, successful, skipped, failed, error_message, metrics = row
        return JobRunStatus(
            run_id=run_id,
            status=str(status),
            successful_items=int(successful),
            skipped_items=int(skipped),
            failed_items=int(failed),
            error_message=error_message,
            metrics=metrics or {},
        )
