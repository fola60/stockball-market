from __future__ import annotations

from uuid import UUID

import psycopg2

from app.topups.models import TopupAuditRecord, TopupCadence, TopupPolicy, TopupRecordStatus


class PostgresTopupRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def list_policies(self, cadence: TopupCadence) -> list[TopupPolicy]:
        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        account_id::text,
                        portfolio_id::text,
                        cadence,
                        amount::text,
                        enabled
                    FROM worker_topup_policies
                    WHERE cadence = %s
                    ORDER BY account_id, portfolio_id
                    """,
                    (cadence.value,),
                )
                rows = cursor.fetchall()

        return [
            TopupPolicy(
                account_id=UUID(account_id),
                portfolio_id=UUID(portfolio_id),
                cadence=TopupCadence(cadence_value),
                amount=amount,
                enabled=enabled,
            )
            for account_id, portfolio_id, cadence_value, amount, enabled in rows
        ]

    def get_record(self, request_id: str) -> TopupAuditRecord | None:
        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        request_id,
                        account_id::text,
                        portfolio_id::text,
                        cadence,
                        amount::text,
                        window_start,
                        window_end_exclusive,
                        status,
                        created_at,
                        updated_at,
                        ledger_entry_id::text,
                        applied_at,
                        retryable,
                        failure_code,
                        failure_message
                    FROM worker_topup_records
                    WHERE request_id = %s
                    """,
                    (request_id,),
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return _row_to_record(row)

    def save_record(self, record: TopupAuditRecord) -> None:
        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO worker_topup_records (
                        request_id,
                        account_id,
                        portfolio_id,
                        cadence,
                        amount,
                        window_start,
                        window_end_exclusive,
                        status,
                        created_at,
                        updated_at,
                        ledger_entry_id,
                        applied_at,
                        retryable,
                        failure_code,
                        failure_message
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (request_id) DO UPDATE
                    SET
                        account_id = EXCLUDED.account_id,
                        portfolio_id = EXCLUDED.portfolio_id,
                        cadence = EXCLUDED.cadence,
                        amount = EXCLUDED.amount,
                        window_start = EXCLUDED.window_start,
                        window_end_exclusive = EXCLUDED.window_end_exclusive,
                        status = EXCLUDED.status,
                        updated_at = EXCLUDED.updated_at,
                        ledger_entry_id = EXCLUDED.ledger_entry_id,
                        applied_at = EXCLUDED.applied_at,
                        retryable = EXCLUDED.retryable,
                        failure_code = EXCLUDED.failure_code,
                        failure_message = EXCLUDED.failure_message
                    """,
                    (
                        record.request_id,
                        str(record.account_id),
                        str(record.portfolio_id),
                        record.cadence.value,
                        record.amount,
                        record.window_start,
                        record.window_end_exclusive,
                        record.status.value,
                        record.created_at,
                        record.updated_at,
                        None if record.ledger_entry_id is None else str(record.ledger_entry_id),
                        record.applied_at,
                        record.retryable,
                        record.failure_code,
                        record.failure_message,
                    ),
                )
            connection.commit()


def _row_to_record(row: tuple[object, ...]) -> TopupAuditRecord:
    (
        request_id,
        account_id,
        portfolio_id,
        cadence_value,
        amount,
        window_start,
        window_end_exclusive,
        status_value,
        created_at,
        updated_at,
        ledger_entry_id,
        applied_at,
        retryable,
        failure_code,
        failure_message,
    ) = row

    return TopupAuditRecord(
        request_id=str(request_id),
        account_id=UUID(str(account_id)),
        portfolio_id=UUID(str(portfolio_id)),
        cadence=TopupCadence(str(cadence_value)),
        amount=str(amount),
        window_start=window_start,
        window_end_exclusive=window_end_exclusive,
        status=TopupRecordStatus(str(status_value)),
        created_at=created_at,
        updated_at=updated_at,
        ledger_entry_id=None if ledger_entry_id is None else UUID(str(ledger_entry_id)),
        applied_at=applied_at,
        retryable=bool(retryable),
        failure_code=None if failure_code is None else str(failure_code),
        failure_message=None if failure_message is None else str(failure_message),
    )
