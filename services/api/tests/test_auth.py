from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.accounts.models import AccountRecord, AccountStatus, AccountType, PortfolioRecord
from app.auth.models import SessionRecord, StoredCredential
from app.auth.passwords import hash_password, verify_password
from app.auth.repository import _account_from_rows
from app.auth.schemas import AuthAccountResponse
from app.auth.service import AuthService, InvalidCredentialsError


class FakeAuthRepository:
    def __init__(self) -> None:
        self.accounts = {}
        self.credentials = {}
        self.sessions = {}
        self.opening_balance = None

    def register_user(self, *, handle, display_name, email, password_hash, opening_balance):
        self.opening_balance = opening_balance
        account_id = uuid4()
        now = datetime.now(UTC)
        account = AccountRecord(
            id=account_id,
            handle=handle,
            email=email,
            display_name=display_name,
            account_type=AccountType.USER,
            status=AccountStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            portfolio=PortfolioRecord(
                id=uuid4(),
                account_id=account_id,
                cash_balance=format(opening_balance, "f"),
                created_at=now,
                updated_at=now,
            ),
        )
        self.accounts[account_id] = account
        self.credentials[email] = StoredCredential(account=account, password_hash=password_hash)
        return account

    def get_credential_by_email(self, email):
        return self.credentials.get(email)

    def create_session(self, account_id, token_hash, expires_at):
        record = SessionRecord(id=uuid4(), account=self.accounts[account_id], expires_at=expires_at)
        self.sessions[token_hash] = record
        return record

    def get_session(self, token_hash, now):
        record = self.sessions.get(token_hash)
        return record if record is not None and record.expires_at > now else None

    def revoke_session(self, token_hash):
        self.sessions.pop(token_hash, None)


class AuthenticationTests(unittest.TestCase):
    def test_repository_normalizes_database_uuid_strings(self) -> None:
        account_id = uuid4()
        portfolio_id = uuid4()
        now = datetime.now(UTC)
        account = _account_from_rows(
            {
                "id": str(account_id),
                "handle": "supporter",
                "email": "user@example.com",
                "display_name": "Stockball Supporter",
                "account_type": "USER",
                "status": "ACTIVE",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": str(portfolio_id),
                "account_id": str(account_id),
                "cash_balance": Decimal("100000.0000"),
                "created_at": now,
                "updated_at": now,
            },
        )

        self.assertEqual(account.id, account_id)
        self.assertEqual(account.portfolio.id, portfolio_id)

    def test_password_hash_is_salted_and_verifiable(self) -> None:
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("correct horse battery staple", first))
        self.assertFalse(verify_password("wrong password", first))
        self.assertFalse(verify_password("anything", "scrypt$n=16384,r=8,p=1$not-base64!$bad"))

    def test_register_login_authenticate_and_logout(self) -> None:
        repository = FakeAuthRepository()
        service = AuthService(repository, opening_balance=Decimal("100000.0000"))
        registered = service.register(
            display_name="Stockball Supporter",
            email="USER@EXAMPLE.COM",
            password="correct horse battery staple",
        )
        self.assertEqual(repository.opening_balance, Decimal("100000.0000"))
        self.assertRegex(registered.account.handle, r"^stockball-supporter-[a-f0-9]{8}$")
        self.assertNotIn("handle", AuthAccountResponse.from_record(registered.account).model_dump())
        principal = service.authenticate(registered.token)
        self.assertEqual(principal.account_id, registered.account.id)

        logged_in = service.login(email="user@example.com", password="correct horse battery staple")
        self.assertEqual(logged_in.account.id, registered.account.id)
        service.logout(logged_in.token)
        self.assertNotIn(
            hashlib.sha256(logged_in.token.encode("utf-8")).hexdigest(), repository.sessions
        )

        with self.assertRaises(InvalidCredentialsError):
            service.login(email="user@example.com", password="incorrect password")


if __name__ == "__main__":
    unittest.main()
