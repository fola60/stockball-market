from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping
from uuid import UUID

from app.database import connection as pooled_connection
from app.jobs.models import JobExecutionResult, JobType

SCHEDULE_OPERATION_TYPES = {
    "weekly-topups": "APPLY_TOPUPS",
    "monthly-topups": "APPLY_TOPUPS",
    "synthetic-trader-ticks": "TICK_SYNTHETIC_TRADERS",
    "daily-player-stats": "INGEST_PLAYER_STATS",
    "bet365-odds": "INGEST_BETTING_MARKETS",
    "bet365-live-odds": "INGEST_BETTING_MARKETS",
    "twitter-injury-intelligence": "INGEST_TWITTER_INJURIES",
    "social-feed-ingestion": "INGEST_SOCIAL_FEEDS",
}


class PostgresScheduledRunRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def create_run(
        self,
        run_id: UUID,
        schedule_name: str,
        window_key: str,
        job_type: JobType,
        parameters: Mapping[str, Any],
        supersede_pending: bool,
    ) -> bool:
        operation_type = SCHEDULE_OPERATION_TYPES[schedule_name]
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                if supersede_pending:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%(schedule_name)s))",
                        {"schedule_name": schedule_name},
                    )
                cursor.execute(
                    """
                    INSERT INTO job_runs (
                        id, operation_type, job_type, source, schedule_name,
                        schedule_window_key, status, parameters
                    )
                    VALUES (
                        %(id)s, %(operation_type)s, %(job_type)s, 'SCHEDULED',
                        %(schedule_name)s, %(window_key)s, 'QUEUED', %(parameters)s::jsonb
                    )
                    ON CONFLICT (schedule_name, schedule_window_key)
                        WHERE source = 'SCHEDULED'
                    DO NOTHING
                    RETURNING id
                    """,
                    {
                        "id": str(run_id),
                        "operation_type": operation_type,
                        "job_type": job_type.value,
                        "schedule_name": schedule_name,
                        "window_key": window_key,
                        "parameters": json.dumps(dict(parameters), default=str),
                    },
                )
                created = cursor.fetchone() is not None
                if created and supersede_pending:
                    cursor.execute(
                        """
                        UPDATE job_runs
                        SET status = 'SUPERSEDED',
                            error_message = 'Superseded by a newer scheduled run before execution',
                            metrics = metrics || jsonb_build_object(
                                'superseded_by_run_id', %(new_run_id)s,
                                'superseded_reason', 'newer_scheduled_run'
                            ),
                            completed_at = now(), updated_at = now()
                        WHERE source = 'SCHEDULED'
                          AND schedule_name = %(schedule_name)s
                          AND status IN ('QUEUED', 'RETRYING')
                          AND id <> %(new_run_id)s
                        """,
                        {
                            "new_run_id": str(run_id),
                            "schedule_name": schedule_name,
                        },
                    )
                return created

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


class PostgresOperationRunReporter:
    def __init__(
        self,
        database_url: str,
        scheduled_realtime_max_lag_seconds: int = 120,
    ) -> None:
        self._database_url = database_url
        self._scheduled_realtime_max_lag = timedelta(
            seconds=scheduled_realtime_max_lag_seconds
        )

    def claim_for_execution(
        self,
        run_id: UUID,
        attempt: int,
        started_at: datetime,
    ) -> bool:
        stale_before = started_at - self._scheduled_realtime_max_lag
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE job_runs
                    SET status = 'SUPERSEDED',
                        error_message = 'Scheduled real-time job expired before execution',
                        metrics = metrics || jsonb_build_object(
                            'superseded_reason', 'stale_scheduled_job',
                            'max_lag_seconds', %(max_lag_seconds)s
                        ),
                        completed_at = now(), updated_at = now()
                    WHERE id = %(id)s
                      AND source = 'SCHEDULED'
                      AND schedule_name IN (
                          'synthetic-trader-ticks',
                          'bet365-live-odds'
                      )
                      AND status IN ('QUEUED', 'RETRYING')
                      AND schedule_window_key::timestamptz < %(stale_before)s
                    RETURNING id
                    """,
                    {
                        "id": str(run_id),
                        "max_lag_seconds": int(
                            self._scheduled_realtime_max_lag.total_seconds()
                        ),
                        "stale_before": stale_before,
                    },
                )
                if cursor.fetchone() is not None:
                    return False

                cursor.execute(
                    """
                    UPDATE job_runs
                    SET status = 'RUNNING', attempt = %(attempt)s,
                        started_at = COALESCE(started_at, %(started_at)s),
                        completed_at = NULL, error_message = NULL, updated_at = now()
                    WHERE id = %(id)s
                      AND status IN ('QUEUED', 'RETRYING')
                    RETURNING id
                    """,
                    {
                        "id": str(run_id),
                        "attempt": attempt,
                        "started_at": started_at,
                    },
                )
                return cursor.fetchone() is not None

    def mark_succeeded(self, run_id: UUID, result: JobExecutionResult, elapsed_ms: int) -> None:
        metrics = {**result.metrics, "elapsed_ms": elapsed_ms}
        self._update(
            """
            UPDATE job_runs
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

    def mark_retrying(
        self,
        run_id: UUID,
        attempt: int,
        error: str,
        result: JobExecutionResult,
    ) -> bool:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE job_runs AS current
                    SET status = 'RETRYING', attempt = %(attempt)s,
                        error_message = %(error)s,
                        successful_items = %(successful)s,
                        skipped_items = %(skipped)s,
                        failed_items = %(failed)s,
                        retryable_failures = %(retryable)s,
                        metrics = %(metrics)s::jsonb, updated_at = now()
                    WHERE current.id = %(id)s
                      AND current.status = 'RUNNING'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM job_runs AS newer
                          WHERE current.source = 'SCHEDULED'
                            AND current.schedule_name IN (
                                'synthetic-trader-ticks',
                                'daily-player-stats',
                                'bet365-odds',
                                'bet365-live-odds',
                                'twitter-injury-intelligence'
                            )
                            AND newer.source = 'SCHEDULED'
                            AND newer.schedule_name = current.schedule_name
                            AND newer.status IN ('QUEUED', 'RETRYING')
                            AND newer.enqueued_at > current.enqueued_at
                      )
                    RETURNING id
                    """,
                    {
                        "id": str(run_id),
                        "attempt": attempt,
                        "error": error[:2000],
                        "successful": result.successful_items,
                        "skipped": result.skipped_items,
                        "failed": result.failed_items,
                        "retryable": result.retryable_failures,
                        "metrics": json.dumps(result.metrics, default=str),
                    },
                )
                if cursor.fetchone() is not None:
                    return True

                cursor.execute(
                    """
                    UPDATE job_runs
                    SET status = 'SUPERSEDED',
                        error_message = 'Retry superseded by a newer scheduled run',
                        metrics = %(metrics)s::jsonb || jsonb_build_object(
                            'superseded_reason', 'newer_scheduled_run'
                        ),
                        completed_at = now(), updated_at = now()
                    WHERE id = %(id)s AND status = 'RUNNING'
                    """,
                    {
                        "id": str(run_id),
                        "metrics": json.dumps(result.metrics, default=str),
                    },
                )
                return False

    def mark_failed(self, run_id: UUID, error: str, result: JobExecutionResult | None = None) -> None:
        result = result or JobExecutionResult(
            job_type=JobType.CHECK_MARKET_FREEZES,
            handled_at=datetime.now(UTC),
            successful_items=0, skipped_items=0, failed_items=1,
        )
        self._update(
            """
            UPDATE job_runs
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
        with pooled_connection(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, parameters)
