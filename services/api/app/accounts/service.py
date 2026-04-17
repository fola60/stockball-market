from __future__ import annotations

from uuid import UUID

from app.accounts.models import AccountRecord, AccountType, CreateAccountCommand
from app.accounts.repository import AccountAlreadyExistsError, AccountsRepository


class AccountNotFoundError(Exception):
    def __init__(self, account_id: UUID) -> None:
        self.account_id = account_id
        super().__init__(f"account {account_id} was not found")


class AccountsService:
    def __init__(self, repository: AccountsRepository) -> None:
        self._repository = repository

    def create_account(self, command: CreateAccountCommand) -> AccountRecord:
        return self._repository.create_account(command)

    def get_account(self, account_id: UUID) -> AccountRecord:
        account = self._repository.get_account(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)
        return account

    def list_accounts(self, account_type: AccountType | None = None) -> list[AccountRecord]:
        return self._repository.list_accounts(account_type)


__all__ = [
    "AccountAlreadyExistsError",
    "AccountNotFoundError",
    "AccountsService",
]
