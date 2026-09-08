from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.accounts.models import AccountRecord, AccountStatus, AccountType, PortfolioRecord


class CreateAccountRequest(BaseModel):
    handle: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=320)

    @field_validator("handle", "display_name")
    @classmethod
    def strip_and_require_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("must be a valid email address")
        return normalized


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    cash_balance: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, portfolio: PortfolioRecord) -> "PortfolioResponse":
        return cls.model_validate(portfolio)


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    handle: str
    email: str | None
    display_name: str
    account_type: AccountType
    status: AccountStatus
    created_at: datetime
    updated_at: datetime
    portfolio: PortfolioResponse

    @classmethod
    def from_record(cls, account: AccountRecord) -> "AccountResponse":
        return cls(
            id=account.id,
            handle=account.handle,
            email=account.email,
            display_name=account.display_name,
            account_type=account.account_type,
            status=account.status,
            created_at=account.created_at,
            updated_at=account.updated_at,
            portfolio=PortfolioResponse.from_record(account.portfolio),
        )
