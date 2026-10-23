from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.accounts.models import AccountRecord, AccountStatus, AccountType, PortfolioRecord
from app.accounts.service import AccountsService
from app.auth.models import SessionRecord, StoredCredential
from app.auth.rate_limits import (
    AuthRateLimits,
    InMemoryRateLimiter,
    RateLimit,
    RateLimitExceededError,
    RedisRateLimiter,
    client_address,
)
from app.auth.service import AuthService
from app.main import create_app


class FakeAuthRepository:
    """Just enough of the auth repository to register, sign in and hold sessions."""

    def __init__(self) -> None:
        self.accounts = {}
        self.credentials = {}
        self.sessions = {}

    def register_user(self, *, handle, display_name, email, password_hash):
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
                cash_balance="0.0000",
                created_at=now,
                updated_at=now,
            ),
        )
        self.accounts[account_id] = account
        self.credentials[email] = StoredCredential(account=account, password_hash=password_hash)
        return account

    def delete_unfunded_registration(self, account_id):
        return False

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


class FakeOpeningBalanceClient:
    def apply_opening_balance(self, *, account_id, portfolio_id, amount):
        return None


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _app(limiter: InMemoryRateLimiter):
    repository = FakeAuthRepository()
    service = AuthService(
        repository,
        trading_engine=FakeOpeningBalanceClient(),
        opening_balance=Decimal("100000.0000"),
    )
    # Any service given stops create_app building the rest from the environment.
    app = create_app(
        accounts_service=AccountsService(None),  # type: ignore[arg-type]
        auth_service=service,
        rate_limiter=limiter,
    )
    app.state.auth_rate_limits = AuthRateLimits(
        register_per_address=RateLimit("register-address", 2, 3600),
        login_per_address=RateLimit("login-address", 5, 900),
        failed_logins_per_email=RateLimit("login-email-failures", 3, 900),
    )
    return app


def _register(client: TestClient, number: int, address: str = "203.0.113.7"):
    return client.post(
        "/v1/auth/register",
        json={
            "display_name": f"Supporter {number}",
            "email": f"user{number}@example.com",
            "password": "correct horse battery staple",
        },
        headers={"X-Forwarded-For": address},
    )


class AuthRateLimitTests(unittest.TestCase):
    def test_sign_ups_are_limited_per_visitor_address(self) -> None:
        clock = Clock()
        client = TestClient(_app(InMemoryRateLimiter(clock)))

        self.assertEqual(_register(client, 1).status_code, 201)
        self.assertEqual(_register(client, 2).status_code, 201)
        limited = _register(client, 3)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["code"], "rate_limited")
        self.assertGreater(int(limited.headers["Retry-After"]), 0)

        # Another visitor behind the same web server is counted separately.
        self.assertEqual(_register(client, 4, address="198.51.100.9").status_code, 201)

        clock.now += 3600
        self.assertEqual(_register(client, 5).status_code, 201)

    def test_failed_logins_lock_the_email_but_not_a_correct_password_beforehand(self) -> None:
        clock = Clock()
        client = TestClient(_app(InMemoryRateLimiter(clock)))
        self.assertEqual(_register(client, 1).status_code, 201)

        def login(password: str, address: str):
            return client.post(
                "/v1/auth/login",
                json={"email": "user1@example.com", "password": password},
                headers={"X-Forwarded-For": address},
            )

        for _ in range(3):
            self.assertEqual(login("correct horse battery staple", "203.0.113.1").status_code, 200)
        for index in range(3):
            self.assertEqual(login("wrong password", f"203.0.113.{10 + index}").status_code, 401)

        # Spreading guesses across addresses does not get past the per-email limit.
        self.assertEqual(login("wrong password", "203.0.113.50").status_code, 429)
        self.assertEqual(login("correct horse battery staple", "203.0.113.51").status_code, 429)

        clock.now += 900
        self.assertEqual(login("correct horse battery staple", "203.0.113.51").status_code, 200)

    def test_login_attempts_are_limited_per_address(self) -> None:
        client = TestClient(_app(InMemoryRateLimiter(Clock())))
        statuses = [
            client.post(
                "/v1/auth/login",
                json={"email": f"nobody{index}@example.com", "password": "guess"},
                headers={"X-Forwarded-For": "203.0.113.99"},
            ).status_code
            for index in range(6)
        ]
        self.assertEqual(statuses, [401, 401, 401, 401, 401, 429])


class ClientAddressTests(unittest.TestCase):
    class _Request:
        def __init__(self, peer: str, forwarded: str | None) -> None:
            self.client = type("Client", (), {"host": peer})()
            self.headers = {"x-forwarded-for": forwarded} if forwarded else {}

    def test_trusts_forwarded_address_only_from_an_internal_peer(self) -> None:
        self.assertEqual(
            client_address(self._Request("172.18.0.5", "203.0.113.7, 10.0.0.1")),  # type: ignore[arg-type]
            "203.0.113.7",
        )
        self.assertEqual(
            client_address(self._Request("8.8.8.8", "203.0.113.7")),  # type: ignore[arg-type]
            "8.8.8.8",
        )


class RedisRateLimiterTests(unittest.TestCase):
    def test_an_unreachable_store_lets_requests_through(self) -> None:
        limiter = RedisRateLimiter("redis://127.0.0.1:1/0")
        rule = RateLimit("test", 1, 60)
        for _ in range(3):
            limiter.hit(rule, "key")
        limiter.check(rule, "key")

    def test_in_memory_limiter_raises_with_retry_after(self) -> None:
        clock = Clock()
        limiter = InMemoryRateLimiter(clock)
        rule = RateLimit("test", 1, 60)
        limiter.hit(rule, "key")
        with self.assertRaises(RateLimitExceededError) as raised:
            limiter.hit(rule, "key")
        self.assertLessEqual(raised.exception.retry_after_seconds, 60)


if __name__ == "__main__":
    unittest.main()
