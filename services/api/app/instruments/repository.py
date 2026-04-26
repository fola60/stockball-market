from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator, Protocol
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.common.decimal import format_decimal
from app.instruments.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
    PriceSnapshotReason,
    PriceSnapshotRecord,
)


class InstrumentsRepository(Protocol):
    def list_instruments(self) -> list[InstrumentRecord]: ...

    def get_instrument(self, instrument_id: UUID) -> InstrumentRecord | None: ...

    def list_price_history(self, instrument_id: UUID) -> list[PriceSnapshotRecord]: ...


class PostgresInstrumentsRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        connection = psycopg2.connect(self._database_url)
        try:
            yield connection
        finally:
            connection.close()

    def list_instruments(self) -> list[InstrumentRecord]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        instrument_type,
                        player_id,
                        symbol,
                        display_name,
                        current_price,
                        shares_outstanding AS quantity_outstanding,
                        price_impact_unit,
                        trading_status AS status,
                        created_at,
                        updated_at
                    FROM instruments
                    ORDER BY created_at DESC, id DESC
                    """
                )
                rows = cursor.fetchall()

        return [_build_instrument_record(row) for row in rows]

    def get_instrument(self, instrument_id: UUID) -> InstrumentRecord | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        instrument_type,
                        player_id,
                        symbol,
                        display_name,
                        current_price,
                        shares_outstanding AS quantity_outstanding,
                        price_impact_unit,
                        trading_status AS status,
                        created_at,
                        updated_at
                    FROM instruments
                    WHERE id = %(instrument_id)s
                    """,
                    {"instrument_id": instrument_id},
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return _build_instrument_record(row)

    def list_price_history(self, instrument_id: UUID) -> list[PriceSnapshotRecord]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        instrument_id,
                        old_price,
                        new_price,
                        reason,
                        trade_id,
                        captured_at
                    FROM price_snapshots
                    WHERE instrument_id = %(instrument_id)s
                    ORDER BY captured_at DESC, id DESC
                    """,
                    {"instrument_id": instrument_id},
                )
                rows = cursor.fetchall()

        return [_build_price_snapshot_record(row) for row in rows]


def _build_instrument_record(row: dict) -> InstrumentRecord:
    return InstrumentRecord(
        id=row["id"],
        instrument_type=InstrumentType(row["instrument_type"]),
        player_id=row["player_id"],
        symbol=row["symbol"],
        display_name=row["display_name"],
        current_price=format_decimal(_as_decimal(row["current_price"])),
        quantity_outstanding=format_decimal(_as_decimal(row["quantity_outstanding"])),
        price_impact_unit=format_decimal(_as_decimal(row["price_impact_unit"])),
        status=InstrumentStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _build_price_snapshot_record(row: dict) -> PriceSnapshotRecord:
    return PriceSnapshotRecord(
        id=row["id"],
        instrument_id=row["instrument_id"],
        old_price=format_decimal(_as_decimal(row["old_price"])),
        new_price=format_decimal(_as_decimal(row["new_price"])),
        reason=PriceSnapshotReason(row["reason"]),
        trade_id=row["trade_id"],
        captured_at=row["captured_at"],
    )


def _as_decimal(value: Decimal) -> Decimal:
    return value
