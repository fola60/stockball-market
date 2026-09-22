from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.accounts.models import AccountRecord, AccountStatus, AccountType
from app.accounts.schemas import PortfolioResponse
from app.auth.models import AuthenticatedSession


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("display_name", "email")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("must be a valid email address")
        return value.lower()


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class AuthAccountResponse(BaseModel):
    """The user-facing account shape; the generated database handle stays internal."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str | None
    display_name: str
    account_type: AccountType
    status: AccountStatus
    created_at: datetime
    updated_at: datetime
    portfolio: PortfolioResponse

    @classmethod
    def from_record(cls, account: AccountRecord) -> "AuthAccountResponse":
        return cls(
            id=account.id,
            email=account.email,
            display_name=account.display_name,
            account_type=account.account_type,
            status=account.status,
            created_at=account.created_at,
            updated_at=account.updated_at,
            portfolio=PortfolioResponse.from_record(account.portfolio),
        )


class AuthSessionResponse(BaseModel):
    session_token: str
    expires_at: datetime
    account: AuthAccountResponse

    @classmethod
    def from_record(cls, session: AuthenticatedSession) -> "AuthSessionResponse":
        return cls(
            session_token=session.token,
            expires_at=session.expires_at,
            account=AuthAccountResponse.from_record(session.account),
        )
