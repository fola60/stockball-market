from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Callable, Mapping, Protocol

from app.jobs.handlers import JobHandler, RetryableJobError, UnknownJobError, WorkerJobRunner
from app.jobs.models import JobExecutionResult, JobType, WorkerJob


class BlockingJobQueue(Protocol):
    def dequeue(self, timeout_seconds: int) -> WorkerJob | None: ...


class RetryQueue(Protocol):
    def schedule(self, job: WorkerJob, available_at: datetime) -> None: ...

    def move_due(self, limit: int = 100) -> int: ...


class OperationRunReporter(Protocol):
    def claim_for_execution(self, run_id, attempt: int, started_at: datetime) -> bool: ...
    def mark_succeeded(self, run_id, result, elapsed_ms: int) -> None: ...
    def mark_retrying(self, run_id, attempt: int, error: str, result) -> bool: ...
    def mark_failed(self, run_id, error: str, result=None) -> None: ...


class ActiveJobReporter(Protocol):
    def mark_job_started(self, job: WorkerJob, started_at: datetime) -> None: ...
    def mark_job_finished(self, job: WorkerJob) -> None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobExecutionTimeoutError(RuntimeError):
    pass


class IsolatedJobExecutionError(RuntimeError):
    pass


@dataclass
class WorkerProcess:
    queue: BlockingJobQueue
    retry_queue: RetryQueue
    runner: WorkerJobRunner
    retry_delay_seconds: int
    max_attempts: int
    clock: Callable[[], datetime] = _utc_now
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))
    operation_reporter: OperationRunReporter | None = None
    active_job_reporter: ActiveJobReporter | None = None
    isolated_job_timeouts: Mapping[JobType, float] = field(default_factory=dict)

    def run_once(self, block_seconds: int) -> bool:
        moved_retry_count = self.retry_queue.move_due()
        if moved_retry_count:
            self.logger.info("moved %s retry jobs back to the main queue", moved_retry_count)

        job = self.queue.dequeue(block_seconds)
        if job is None:
            return False

        started_at = self.clock()
        started = monotonic()
        if (
            job.operation_run_id is not None
            and self.operation_reporter is not None
            and not self.operation_reporter.claim_for_execution(
                job.operation_run_id,
                job.attempt,
                started_at,
            )
        ):
            self.logger.info(
                "discarded non-executable worker job %s run_id=%s attempt=%s",
                job.job_type.value,
                job.operation_run_id,
                job.attempt,
            )
            return True
        if self.active_job_reporter is not None:
            self.active_job_reporter.mark_job_started(job, started_at)
        try:
            return self._run_job(job, started)
        finally:
            if self.active_job_reporter is not None:
                self.active_job_reporter.mark_job_finished(job)

    def _run_job(self, job: WorkerJob, started: float) -> bool:
        try:
            timeout_seconds = self.isolated_job_timeouts.get(job.job_type)
            result = (
                self.runner.run(job)
                if timeout_seconds is None
                else _run_isolated(
                    self.runner.handler_for(job.job_type),
                    job,
                    timeout_seconds,
                )
            )
        except RetryableJobError as exc:
            self._handle_retryable_failure(job, exc)
            return True
        except JobExecutionTimeoutError as exc:
            self.logger.error(
                "worker job %s exceeded its execution timeout",
                job.job_type.value,
            )
            self._mark_failed(job, str(exc))
            return True
        except UnknownJobError as exc:
            self.logger.exception("dropping unknown worker job type %s", job.job_type.value)
            self._mark_failed(job, str(exc))
            return True
        except Exception as exc:
            self.logger.exception(
                "worker job %s failed with an unexpected non-retryable error",
                job.job_type.value,
            )
            self._mark_failed(job, str(exc))
            return True

        elapsed_ms = round((monotonic() - started) * 1000)
        if job.operation_run_id is not None and self.operation_reporter is not None:
            self.operation_reporter.mark_succeeded(job.operation_run_id, result, elapsed_ms)

        self.logger.info(
            "completed worker job %s run_id=%s attempt=%s elapsed_ms=%s success=%s skipped=%s failed=%s metrics=%s",
            job.job_type.value,
            job.operation_run_id,
            job.attempt,
            elapsed_ms,
            result.successful_items,
            result.skipped_items,
            result.failed_items,
            dict(result.metrics),
            extra={"operation_run_id": str(job.operation_run_id) if job.operation_run_id else None,
                   "elapsed_ms": elapsed_ms, "metrics": dict(result.metrics)},
        )
        return True

    def run_forever(self, block_seconds: int) -> None:
        while True:
            self.run_once(block_seconds)

    def _handle_retryable_failure(self, job: WorkerJob, error: RetryableJobError) -> None:
        next_attempt = job.attempt + 1
        if next_attempt >= self.max_attempts:
            self.logger.error(
                "worker job %s exhausted retries at attempt=%s retryable_failures=%s",
                job.job_type.value,
                next_attempt,
                error.result.retryable_failures,
            )
            self._mark_failed(job, str(error), error.result)
            return

        available_at = self.clock() + timedelta(seconds=self.retry_delay_seconds)
        should_retry = True
        if job.operation_run_id is not None and self.operation_reporter is not None:
            should_retry = self.operation_reporter.mark_retrying(
                job.operation_run_id, next_attempt, str(error), error.result
            )
        if not should_retry:
            self.logger.info(
                "did not retry superseded worker job %s run_id=%s",
                job.job_type.value,
                job.operation_run_id,
            )
            return
        self.retry_queue.schedule(job.with_attempt(next_attempt), available_at)
        self.logger.warning(
            "scheduled retry for job %s attempt=%s available_at=%s",
            job.job_type.value,
            next_attempt,
            available_at.isoformat(),
        )

    def _mark_failed(self, job: WorkerJob, error: str, result=None) -> None:
        if job.operation_run_id is not None and self.operation_reporter is not None:
            self.operation_reporter.mark_failed(job.operation_run_id, error, result)


def _run_isolated(
    handler: JobHandler,
    job: WorkerJob,
    timeout_seconds: float,
) -> JobExecutionResult:
    if timeout_seconds <= 0:
        raise ValueError("isolated job timeout must be positive")

    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_isolated_job_main,
        args=(child_connection, handler, job),
        name=f"stockball-{job.job_type.value.lower()}",
    )
    process.start()
    child_connection.close()
    deadline = monotonic() + timeout_seconds
    try:
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                _terminate_isolated_process(process)
                raise JobExecutionTimeoutError(
                    f"{job.job_type.value} exceeded {timeout_seconds:g} seconds"
                )
            if parent_connection.poll(min(remaining, 0.1)):
                outcome = parent_connection.recv()
                break
            if not process.is_alive():
                process.join(timeout=0)
                raise IsolatedJobExecutionError(
                    f"{job.job_type.value} process exited without a result"
                )
    finally:
        parent_connection.close()

    process.join(timeout=3)
    if process.is_alive():
        _terminate_isolated_process(process)

    outcome_type = outcome[0]
    if outcome_type == "succeeded":
        return outcome[1]
    if outcome_type == "retryable":
        raise RetryableJobError(outcome[1], outcome[2])
    if outcome_type == "unknown":
        raise UnknownJobError(outcome[1])
    raise IsolatedJobExecutionError(outcome[1])


def _isolated_job_main(connection, handler: JobHandler, job: WorkerJob) -> None:
    try:
        os.setsid()
        try:
            connection.send(("succeeded", handler.handle(job)))
        except RetryableJobError as error:
            connection.send(("retryable", str(error), error.result))
        except UnknownJobError as error:
            connection.send(("unknown", str(error)))
        except Exception as error:
            connection.send(
                (
                    "failed",
                    f"{type(error).__name__}: {error}\n{traceback.format_exc()}",
                )
            )
    finally:
        connection.close()


def _terminate_isolated_process(process: multiprocessing.Process) -> None:
    if process.pid is None or not process.is_alive():
        process.join(timeout=0)
        return

    try:
        process_group = os.getpgid(process.pid)
    except ProcessLookupError:
        process.join(timeout=0)
        return

    if process_group == process.pid:
        os.killpg(process_group, signal.SIGTERM)
    else:
        process.terminate()
    process.join(timeout=3)
    if not process.is_alive():
        return
    if process_group == process.pid:
        os.killpg(process_group, signal.SIGKILL)
    else:
        process.kill()
    process.join(timeout=3)
