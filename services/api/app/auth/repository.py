from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Protocol
from uuid import UUID

import psycopg2
from psycopg2 import errors
from psycopg2.extras import RealDictCursor

from app.accounts.models import AccountRecord, AccountStatus, AccountType, PortfolioRecord
from app.accounts.repository import AccountAlreadyExistsError
from app.auth.models import SessionRecord, StoredCredential
from app.database import connection as pooled_connection


class AuthRepository(Protocol):
    def register_user(
        self,
        *,
        handle: str,
        display_name: str,
        email: str,
        password_hash: str,
    ) -> AccountRecord: ...

    def delete_unfunded_registration(self, account_id: UUID) -> bool: ...

    def get_credential_by_email(self, email: str) -> StoredCredential | None: ...

    def create_session(
        self, account_id: UUID, token_hash: str, expires_at: datetime
    ) -> SessionRecord: ...

    def get_session(self, token_hash: str, now: datetime) -> SessionRecord | None: ...

    def revoke_session(self, token_hash: str) -> None: ...


class PostgresAuthRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def register_user(
        self,
        *,
        handle: str,
        display_name: str,
        email: str,
        password_hash: str,
    ) -> AccountRecord:
        # The portfolio starts empty: its opening balance is a cash movement, which only the
        # trading engine may make (see AuthService.register).
        try:
            with self._connection() as connection:
                with connection:
                    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                        cursor.execute(
                            """
                            INSERT INTO accounts (handle, email, display_name, account_type)
                            VALUES (%(handle)s, %(email)s, %(display_name)s, 'USER')
                            RETURNING id, handle, email, display_name, account_type, status,
                                      created_at, updated_at
                            """,
                            {"handle": handle, "email": email, "display_name": display_name},
                        )
                        account_row = cursor.fetchone()
                        if account_row is None:
                            raise RuntimeError("account insert returned no row")

                        cursor.execute(
                            """
                            INSERT INTO portfolios (account_id)
                            VALUES (%(account_id)s)
                            RETURNING id, account_id, cash_balance, created_at, updated_at
                            """,
                            {"account_id": account_row["id"]},
                        )
                        portfolio_row = cursor.fetchone()
                        if portfolio_row is None:
                            raise RuntimeError("portfolio insert returned no row")

                        cursor.execute(
                            """
                            INSERT INTO auth_credentials (account_id, password_hash)
                            VALUES (%(account_id)s, %(password_hash)s)
                            """,
                            {"account_id": account_row["id"], "password_hash": password_hash},
                        )
        except errors.UniqueViolation as exc:
            constraint = exc.diag.constraint_name
            if constraint == "accounts_handle_key":
                raise AccountAlreadyExistsError("handle", handle) from exc
            if constraint == "accounts_email_key":
                raise AccountAlreadyExistsError("email", email) from exc
            raise

        return _account_from_rows(account_row, portfolio_row)

    def delete_unfunded_registration(self, account_id: UUID) -> bool:
        """Undo a registration whose opening balance never landed.

        Returns False, leaving the account in place, when the portfolio already has ledger
        history: the engine credited it even though its response was lost.
        """
        with self._connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT p.id
                        FROM portfolios p
                        WHERE p.account_id = %(account_id)s
                        FOR UPDATE
                        """,
                        {"account_id": str(account_id)},
                    )
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM cash_ledger_entries WHERE account_id = %(account_id)s
                        )
                        """,
                        {"account_id": str(account_id)},
                    )
                    row = cursor.fetchone()
                    if row is not None and row[0]:
                        return False
                    for statement in (
                        "DELETE FROM user_sessions WHERE account_id = %(account_id)s",
                        "DELETE FROM auth_credentials WHERE account_id = %(account_id)s",
                        "DELETE FROM portfolios WHERE account_id = %(account_id)s",
                        "DELETE FROM accounts WHERE id = %(account_id)s",
                    ):
                        cursor.execute(statement, {"account_id": str(account_id)})
        return True

    def get_credential_by_email(self, email: str) -> StoredCredential | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT a.id, a.handle, a.email, a.display_name, a.account_type, a.status,
                           a.created_at, a.updated_at, c.password_hash,
                           p.id AS portfolio_id, p.account_id AS portfolio_account_id,
                           p.cash_balance AS portfolio_cash_balance,
                           p.created_at AS portfolio_created_at,
                           p.updated_at AS portfolio_updated_at
                    FROM accounts a
                    JOIN auth_credentials c ON c.account_id = a.id
                    JOIN portfolios p ON p.account_id = a.id
                    WHERE lower(a.email) = lower(%(email)s)
                    """,
                    {"email": email},
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return StoredCredential(account=_account_from_join(row), password_hash=row["password_hash"])

    def create_session(
        self, account_id: UUID, token_hash: str, expires_at: datetime
    ) -> SessionRecord:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO user_sessions (account_id, token_hash, expires_at)
                    VALUES (%(account_id)s, %(token_hash)s, %(expires_at)s)
                    RETURNING id
                    """,
                    {"account_id": str(account_id), "token_hash": token_hash, "expires_at": expires_at},
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("session insert returned no row")
        credential = self._get_account(account_id)
        return SessionRecord(
            id=UUID(str(row["id"])), account=credential, expires_at=expires_at
        )

    def get_session(self, token_hash: str, now: datetime) -> SessionRecord | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE user_sessions s
                    SET last_seen_at = %(now)s
                    FROM accounts a, portfolios p
                    WHERE s.token_hash = %(token_hash)s
                      AND s.revoked_at IS NULL
                      AND s.expires_at > %(now)s
                      AND a.id = s.account_id
                      AND p.account_id = a.id
                    RETURNING s.id AS session_id, s.expires_at,
                              a.id, a.handle, a.email, a.display_name, a.account_type,
                              a.status, a.created_at, a.updated_at,
                              p.id AS portfolio_id, p.account_id AS portfolio_account_id,
                              p.cash_balance AS portfolio_cash_balance,
                              p.created_at AS portfolio_created_at,
                              p.updated_at AS portfolio_updated_at
                    """,
                    {"token_hash": token_hash, "now": now},
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return SessionRecord(
            id=UUID(str(row["session_id"])),
            account=_account_from_join(row),
            expires_at=row["expires_at"],
        )

    def revoke_session(self, token_hash: str) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE user_sessions SET revoked_at = now()
                    WHERE token_hash = %s AND revoked_at IS NULL
                    """,
                    (token_hash,),
                )

    def _get_account(self, account_id: UUID) -> AccountRecord:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT a.id, a.handle, a.email, a.display_name, a.account_type, a.status,
                           a.created_at, a.updated_at,
                           p.id AS portfolio_id, p.account_id AS portfolio_account_id,
                           p.cash_balance AS portfolio_cash_balance,
                           p.created_at AS portfolio_created_at,
                           p.updated_at AS portfolio_updated_at
                    FROM accounts a JOIN portfolios p ON p.account_id = a.id
                    WHERE a.id = %s
                    """,
                    (str(account_id),),
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("session account was not found")
        return _account_from_join(row)


def _account_from_rows(account: dict, portfolio: dict) -> AccountRecord:
    return AccountRecord(
        id=UUID(str(account["id"])),
        handle=account["handle"],
        email=account["email"],
        display_name=account["display_name"],
        account_type=AccountType(account["account_type"]),
        status=AccountStatus(account["status"]),
        created_at=account["created_at"],
        updated_at=account["updated_at"],
        portfolio=PortfolioRecord(
            id=UUID(str(portfolio["id"])),
            account_id=UUID(str(portfolio["account_id"])),
            cash_balance=format(portfolio["cash_balance"], "f"),
            created_at=portfolio["created_at"],
            updated_at=portfolio["updated_at"],
        ),
    )


def _account_from_join(row: dict) -> AccountRecord:
    return _account_from_rows(
        row,
        {
            "id": row["portfolio_id"],
            "account_id": row["portfolio_account_id"],
            "cash_balance": row["portfolio_cash_balance"],
            "created_at": row["portfolio_created_at"],
            "updated_at": row["portfolio_updated_at"],
        },
    )
