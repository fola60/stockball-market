from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.accounts.models import AccountRecord, AccountType


@dataclass(frozen=True)
class CurrentPrincipal:
    account_id: UUID
    portfolio_id: UUID
    account_type: AccountType
    session_id: UUID


@dataclass(frozen=True)
class AuthenticatedSession:
    token: str
    expires_at: datetime
    account: AccountRecord


@dataclass(frozen=True)
class StoredCredential:
    account: AccountRecord
    password_hash: str


@dataclass(frozen=True)
class SessionRecord:
    id: UUID
    account: AccountRecord
    expires_at: datetime
