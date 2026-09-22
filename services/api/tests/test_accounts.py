from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.accounts.models import (
    AccountRecord,
    AccountStatus,
    AccountType,
    CreateAccountCommand,
    PortfolioRecord,
)
from app.accounts.repository import AccountAlreadyExistsError
from app.accounts.service import AccountsService
from app.auth.dependencies import get_current_principal
from app.auth.models import CurrentPrincipal
from app.main import create_app


class FakeAccountsRepository:
    def __init__(self) -> None:
        self._accounts: dict[UUID, AccountRecord] = {}
        self.last_create_command: CreateAccountCommand | None = None

    def create_account(self, command: CreateAccountCommand) -> AccountRecord:
        self.last_create_command = command
        if any(account.handle == command.handle for account in self._accounts.values()):
            raise AccountAlreadyExistsError("handle", command.handle)
        if command.email and any(
            account.email == command.email for account in self._accounts.values()
        ):
            raise AccountAlreadyExistsError("email", command.email)

        account_id = uuid4()
        account = AccountRecord(
            id=account_id,
            handle=command.handle,
            email=command.email,
            display_name=command.display_name,
            account_type=command.account_type,
            status=AccountStatus.ACTIVE,
            created_at=_timestamp(),
            updated_at=_timestamp(),
            portfolio=PortfolioRecord(
                id=uuid4(),
                account_id=account_id,
                cash_balance="0.0000",
                created_at=_timestamp(),
                updated_at=_timestamp(),
            ),
        )
        self._accounts[account_id] = account
        return account

    def get_account(self, account_id: UUID) -> AccountRecord | None:
        return self._accounts.get(account_id)

    def list_accounts(self, account_type: AccountType | None = None) -> list[AccountRecord]:
        accounts = list(self._accounts.values())
        if account_type is not None:
            accounts = [
                account for account in accounts if account.account_type == account_type
            ]
        return accounts


class AccountsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeAccountsRepository()
        app = create_app(AccountsService(self.repository))
        app.dependency_overrides[get_current_principal] = lambda: CurrentPrincipal(
            account_id=uuid4(),
            portfolio_id=uuid4(),
            account_type=AccountType.ADMIN,
            session_id=uuid4(),
        )
        self.client = TestClient(app)

    def test_create_synthetic_trader_creates_portfolio_and_returns_201(self) -> None:
        response = self.client.post(
            "/internal/v1/accounts/synthetic-traders",
            json={
                "handle": "bot-1",
                "display_name": "Bot One",
            },
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["handle"], "bot-1")
        self.assertEqual(body["account_type"], "SYNTHETIC_TRADER")
        self.assertEqual(body["portfolio"]["account_id"], body["id"])
        self.assertEqual(body["portfolio"]["cash_balance"], "0.0000")
        self.assertIsNotNone(self.repository.last_create_command)
        self.assertEqual(
            self.repository.last_create_command.account_type,
            AccountType.SYNTHETIC_TRADER,
        )

    def test_list_accounts_supports_account_type_filter(self) -> None:
        user = self.repository.create_account(
            CreateAccountCommand(
                handle="user-1",
                display_name="User One",
                email="user-1@example.com",
                account_type=AccountType.USER,
            )
        )
        synthetic = self.repository.create_account(
            CreateAccountCommand(
                handle="bot-1",
                display_name="Bot One",
                email=None,
                account_type=AccountType.SYNTHETIC_TRADER,
            )
        )

        response = self.client.get("/v1/accounts", params={"account_type": "SYNTHETIC_TRADER"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([item["id"] for item in body], [str(synthetic.id)])
        self.assertNotIn(str(user.id), [item["id"] for item in body])

    def test_get_account_returns_404_when_missing(self) -> None:
        response = self.client.get(f"/v1/accounts/{uuid4()}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "account_not_found")

    def test_create_user_returns_409_on_duplicate_handle(self) -> None:
        self.repository.create_account(
            CreateAccountCommand(
                handle="dupe",
                display_name="First",
                email="first@example.com",
                account_type=AccountType.USER,
            )
        )

        response = self.client.post(
            "/v1/accounts/users",
            json={
                "handle": "dupe",
                "display_name": "Second",
                "email": "second@example.com",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "handle_already_exists")

    def test_create_admin_route_creates_admin_account(self) -> None:
        response = self.client.post(
            "/v1/accounts/admins",
            json={
                "handle": "admin-1",
                "display_name": "Admin One",
                "email": "admin-1@example.com",
            },
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["account_type"], "ADMIN")

    def test_get_account_returns_created_account(self) -> None:
        account = self.repository.create_account(
            CreateAccountCommand(
                handle="reader",
                display_name="Reader",
                email="reader@example.com",
                account_type=AccountType.USER,
            )
        )

        response = self.client.get(f"/v1/accounts/{account.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(account.id))
        self.assertEqual(response.json()["portfolio"]["id"], str(account.portfolio.id))


def _timestamp() -> datetime:
    return datetime.now(tz=UTC)


if __name__ == "__main__":
    unittest.main()
