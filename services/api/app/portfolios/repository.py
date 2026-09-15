from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator, Protocol
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.common.decimal import format_decimal
from app.database import connection as pooled_connection
from app.portfolios.models import PortfolioActivityRecord, PortfolioRecord, PositionRecord


class PortfoliosRepository(Protocol):
    def get_portfolio(self, portfolio_id: UUID) -> PortfolioRecord | None: ...

    def list_activity(self, portfolio_id: UUID, limit: int) -> list[PortfolioActivityRecord]: ...


class PostgresPortfoliosRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def get_portfolio(self, portfolio_id: UUID) -> PortfolioRecord | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        account_id,
                        cash_balance,
                        created_at,
                        updated_at
                    FROM portfolios
                    WHERE id = %(portfolio_id)s
                    """,
                    {"portfolio_id": str(portfolio_id)},
                )
                portfolio_row = cursor.fetchone()

                if portfolio_row is None:
                    return None

                cursor.execute(
                    """
                    SELECT
                        id,
                        portfolio_id,
                        instrument_id,
                        quantity,
                        created_at,
                        updated_at
                    FROM positions
                    WHERE portfolio_id = %(portfolio_id)s
                      AND quantity > 0
                    ORDER BY updated_at DESC, id DESC
                    """,
                    {"portfolio_id": str(portfolio_id)},
                )
                position_rows = cursor.fetchall()

        return PortfolioRecord(
            id=portfolio_row["id"],
            account_id=portfolio_row["account_id"],
            cash_balance=format_decimal(_as_decimal(portfolio_row["cash_balance"])),
            created_at=portfolio_row["created_at"],
            updated_at=portfolio_row["updated_at"],
            positions=[_build_position_record(row) for row in position_rows],
        )

    def list_activity(self, portfolio_id: UUID, limit: int) -> list[PortfolioActivityRecord]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        t.id,
                        t.instrument_id,
                        i.symbol,
                        p.display_name AS player_name,
                        t.side,
                        t.shares,
                        t.execution_price,
                        t.gross_amount,
                        t.executed_at
                    FROM trades AS t
                    JOIN instruments AS i ON i.id = t.instrument_id
                    JOIN players AS p ON p.id = i.player_id
                    WHERE t.portfolio_id = %(portfolio_id)s
                    ORDER BY t.executed_at DESC, t.id DESC
                    LIMIT %(limit)s
                    """,
                    {"portfolio_id": str(portfolio_id), "limit": limit},
                )
                rows = cursor.fetchall()

        return [
            PortfolioActivityRecord(
                id=row["id"],
                instrument_id=row["instrument_id"],
                symbol=row["symbol"],
                player_name=row["player_name"],
                side=row["side"],
                shares=format_decimal(_as_decimal(row["shares"])),
                execution_price=format_decimal(_as_decimal(row["execution_price"])),
                gross_amount=format_decimal(_as_decimal(row["gross_amount"])),
                executed_at=row["executed_at"],
            )
            for row in rows
        ]


def _build_position_record(row: dict) -> PositionRecord:
    return PositionRecord(
        id=row["id"],
        portfolio_id=row["portfolio_id"],
        instrument_id=row["instrument_id"],
        quantity=format_decimal(_as_decimal(row["quantity"])),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _as_decimal(value: Decimal) -> Decimal:
    return value
