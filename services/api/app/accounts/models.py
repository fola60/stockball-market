from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AccountType(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"
    SYNTHETIC_TRADER = "SYNTHETIC_TRADER"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class PortfolioRecord:
    id: UUID
    account_id: UUID
    cash_balance: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AccountRecord:
    id: UUID
    handle: str
    email: str | None
    display_name: str
    account_type: AccountType
    status: AccountStatus
    created_at: datetime
    updated_at: datetime
    portfolio: PortfolioRecord


@dataclass(frozen=True)
class CreateAccountCommand:
    handle: str
    display_name: str
    email: str | None
    account_type: AccountType
