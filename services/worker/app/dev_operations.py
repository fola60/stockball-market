from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import UUID

import psycopg2

from app.jobs.models import JobExecutionResult, JobType


class PostgresOperationRunReporter:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def mark_running(self, run_id: UUID, attempt: int) -> None:
        self._update(
            """
            UPDATE dev_operation_runs
            SET status = 'RUNNING', attempt = %(attempt)s,
                started_at = COALESCE(started_at, now()), error_message = NULL, updated_at = now()
            WHERE id = %(id)s
            """,
            {"id": str(run_id), "attempt": attempt},
        )

    def mark_succeeded(self, run_id: UUID, result: JobExecutionResult, elapsed_ms: int) -> None:
        metrics = {**result.metrics, "elapsed_ms": elapsed_ms}
        self._update(
            """
            UPDATE dev_operation_runs
            SET status = 'SUCCEEDED', successful_items = %(successful)s,
                skipped_items = %(skipped)s, failed_items = %(failed)s,
                retryable_failures = %(retryable)s, metrics = %(metrics)s::jsonb,
                completed_at = now(), updated_at = now()
            WHERE id = %(id)s
            """,
            {
                "id": str(run_id), "successful": result.successful_items,
                "skipped": result.skipped_items, "failed": result.failed_items,
                "retryable": result.retryable_failures, "metrics": json.dumps(metrics, default=str),
            },
        )

    def mark_retrying(self, run_id: UUID, attempt: int, error: str, result: JobExecutionResult) -> None:
        self._update(
            """
            UPDATE dev_operation_runs
            SET status = 'RETRYING', attempt = %(attempt)s, error_message = %(error)s,
                successful_items = %(successful)s, skipped_items = %(skipped)s,
                failed_items = %(failed)s, retryable_failures = %(retryable)s,
                metrics = %(metrics)s::jsonb, updated_at = now()
            WHERE id = %(id)s
            """,
            {
                "id": str(run_id), "attempt": attempt, "error": error[:2000],
                "successful": result.successful_items, "skipped": result.skipped_items,
                "failed": result.failed_items, "retryable": result.retryable_failures,
                "metrics": json.dumps(result.metrics, default=str),
            },
        )

    def mark_failed(self, run_id: UUID, error: str, result: JobExecutionResult | None = None) -> None:
        result = result or JobExecutionResult(
            job_type=JobType.CHECK_MARKET_FREEZES,
            handled_at=datetime.now(UTC),
            successful_items=0, skipped_items=0, failed_items=1,
        )
        self._update(
            """
            UPDATE dev_operation_runs
            SET status = 'FAILED', error_message = %(error)s,
                successful_items = %(successful)s, skipped_items = %(skipped)s,
                failed_items = %(failed)s, retryable_failures = %(retryable)s,
                metrics = %(metrics)s::jsonb, completed_at = now(), updated_at = now()
            WHERE id = %(id)s
            """,
            {
                "id": str(run_id), "error": error[:2000],
                "successful": result.successful_items, "skipped": result.skipped_items,
                "failed": max(1, result.failed_items), "retryable": result.retryable_failures,
                "metrics": json.dumps(result.metrics, default=str),
            },
        )

    def _update(self, query: str, parameters: Mapping[str, Any]) -> None:
        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, parameters)
