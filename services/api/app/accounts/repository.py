from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator, Protocol
from uuid import UUID

import psycopg2
from psycopg2 import errors
from psycopg2.extras import RealDictCursor

from app.accounts.models import (
    AccountRecord,
    AccountStatus,
    AccountType,
    CreateAccountCommand,
    PortfolioRecord,
)
from app.database import connection as pooled_connection


class AccountsRepository(Protocol):
    def create_account(self, command: CreateAccountCommand) -> AccountRecord: ...

    def get_account(self, account_id: UUID) -> AccountRecord | None: ...

    def list_accounts(self, account_type: AccountType | None = None) -> list[AccountRecord]: ...


class AccountAlreadyExistsError(Exception):
    def __init__(self, field_name: str, value: str) -> None:
        self.field_name = field_name
        self.value = value
        super().__init__(f"account with {field_name} '{value}' already exists")


class PostgresAccountsRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def create_account(self, command: CreateAccountCommand) -> AccountRecord:
        try:
            with self._connection() as connection:
                with connection:
                    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                        cursor.execute(
                            """
                            INSERT INTO accounts (
                                handle,
                                email,
                                display_name,
                                account_type
                            ) VALUES (
                                %(handle)s,
                                %(email)s,
                                %(display_name)s,
                                %(account_type)s
                            )
                            RETURNING
                                id,
                                handle,
                                email,
                                display_name,
                                account_type,
                                status,
                                created_at,
                                updated_at
                            """,
                            {
                                "handle": command.handle,
                                "email": command.email,
                                "display_name": command.display_name,
                                "account_type": command.account_type.value,
                            },
                        )
                        account_row = cursor.fetchone()
                        if account_row is None:
                            raise RuntimeError("account insert returned no row")

                        cursor.execute(
                            """
                            INSERT INTO portfolios (
                                account_id
                            ) VALUES (
                                %(account_id)s
                            )
                            RETURNING
                                id,
                                account_id,
                                cash_balance,
                                created_at,
                                updated_at
                            """,
                            {"account_id": account_row["id"]},
                        )
                        portfolio_row = cursor.fetchone()
                        if portfolio_row is None:
                            raise RuntimeError("portfolio insert returned no row")
        except errors.UniqueViolation as exc:
            raise self._map_unique_violation(exc, command) from exc

        return _build_account_record(account_row, portfolio_row)

    def get_account(self, account_id: UUID) -> AccountRecord | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        a.id,
                        a.handle,
                        a.email,
                        a.display_name,
                        a.account_type,
                        a.status,
                        a.created_at,
                        a.updated_at,
                        p.id AS portfolio_id,
                        p.account_id AS portfolio_account_id,
                        p.cash_balance AS portfolio_cash_balance,
                        p.created_at AS portfolio_created_at,
                        p.updated_at AS portfolio_updated_at
                    FROM accounts AS a
                    JOIN portfolios AS p
                        ON p.account_id = a.id
                    WHERE a.id = %(account_id)s
                    """,
                    {"account_id": str(account_id)},
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return _build_account_from_join(row)

    def list_accounts(self, account_type: AccountType | None = None) -> list[AccountRecord]:
        params: dict[str, str] = {}
        where_clause = ""
        if account_type is not None:
            where_clause = "WHERE a.account_type = %(account_type)s"
            params["account_type"] = account_type.value

        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    SELECT
                        a.id,
                        a.handle,
                        a.email,
                        a.display_name,
                        a.account_type,
                        a.status,
                        a.created_at,
                        a.updated_at,
                        p.id AS portfolio_id,
                        p.account_id AS portfolio_account_id,
                        p.cash_balance AS portfolio_cash_balance,
                        p.created_at AS portfolio_created_at,
                        p.updated_at AS portfolio_updated_at
                    FROM accounts AS a
                    JOIN portfolios AS p
                        ON p.account_id = a.id
                    {where_clause}
                    ORDER BY a.created_at DESC, a.id DESC
                    """,
                    params,
                )
                rows = cursor.fetchall()

        return [_build_account_from_join(row) for row in rows]

    def _map_unique_violation(
        self, exc: errors.UniqueViolation, command: CreateAccountCommand
    ) -> AccountAlreadyExistsError:
        constraint_name = exc.diag.constraint_name
        if constraint_name == "accounts_handle_key":
            return AccountAlreadyExistsError("handle", command.handle)
        if constraint_name == "accounts_email_key" and command.email is not None:
            return AccountAlreadyExistsError("email", command.email)
        raise AccountAlreadyExistsError("account", command.handle)


def _build_account_from_join(row: dict) -> AccountRecord:
    portfolio = PortfolioRecord(
        id=row["portfolio_id"],
        account_id=row["portfolio_account_id"],
        cash_balance=_format_decimal(row["portfolio_cash_balance"]),
        created_at=row["portfolio_created_at"],
        updated_at=row["portfolio_updated_at"],
    )
    return AccountRecord(
        id=row["id"],
        handle=row["handle"],
        email=row["email"],
        display_name=row["display_name"],
        account_type=AccountType(row["account_type"]),
        status=AccountStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        portfolio=portfolio,
    )


def _build_account_record(account_row: dict, portfolio_row: dict) -> AccountRecord:
    portfolio = PortfolioRecord(
        id=portfolio_row["id"],
        account_id=portfolio_row["account_id"],
        cash_balance=_format_decimal(portfolio_row["cash_balance"]),
        created_at=portfolio_row["created_at"],
        updated_at=portfolio_row["updated_at"],
    )
    return AccountRecord(
        id=account_row["id"],
        handle=account_row["handle"],
        email=account_row["email"],
        display_name=account_row["display_name"],
        account_type=AccountType(account_row["account_type"]),
        status=AccountStatus(account_row["status"]),
        created_at=account_row["created_at"],
        updated_at=account_row["updated_at"],
        portfolio=portfolio,
    )


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")
