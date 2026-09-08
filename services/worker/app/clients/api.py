from __future__ import annotations

import atexit
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Protocol
from uuid import UUID

import httpx


class AccountType(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"
    SYNTHETIC_TRADER = "SYNTHETIC_TRADER"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class ApiEndpoints:
    create_synthetic_trader: str = "/internal/v1/accounts/synthetic-traders"


@dataclass(frozen=True)
class CreateSyntheticTraderAccountCommand:
    handle: str
    display_name: str
    email: str | None = None

    def to_payload(self) -> dict[str, str | None]:
        return {
            "handle": self.handle,
            "display_name": self.display_name,
            "email": self.email,
        }


@dataclass(frozen=True)
class PortfolioRecord:
    id: UUID
    account_id: UUID
    cash_balance: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "PortfolioRecord":
        return cls(
            id=UUID(str(payload["id"])),
            account_id=UUID(str(payload["account_id"])),
            cash_balance=str(payload["cash_balance"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        )


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

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AccountRecord":
        return cls(
            id=UUID(str(payload["id"])),
            handle=str(payload["handle"]),
            email=None if payload.get("email") is None else str(payload["email"]),
            display_name=str(payload["display_name"]),
            account_type=AccountType(str(payload["account_type"])),
            status=AccountStatus(str(payload["status"])),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            updated_at=datetime.fromisoformat(str(payload["updated_at"])),
            portfolio=PortfolioRecord.from_payload(payload["portfolio"]),
        )


class ApiClient(Protocol):
    def create_synthetic_trader_account(
        self,
        command: CreateSyntheticTraderAccountCommand,
    ) -> AccountRecord: ...


class ApiClientError(Exception):
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(body.get("message", "api request failed"))

    @property
    def retryable(self) -> bool:
        return self.status_code >= 500 or self.status_code in {408, 429}


class ApiUnavailableError(Exception):
    pass


class HttpApiClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        endpoints: ApiEndpoints | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._endpoints = endpoints or ApiEndpoints()
        self._transport = transport
        self._client = httpx.Client(
            timeout=self._timeout_seconds,
            transport=self._transport,
        )
        atexit.register(self.close)

    def close(self) -> None:
        if not self._client.is_closed:
            self._client.close()

    def create_synthetic_trader_account(
        self,
        command: CreateSyntheticTraderAccountCommand,
    ) -> AccountRecord:
        payload = self._post(
            self._endpoints.create_synthetic_trader,
            command.to_payload(),
        )
        return AccountRecord.from_payload(payload)

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(f"{self._base_url}{path}", json=dict(payload))
        except httpx.HTTPError as exc:
            raise ApiUnavailableError("api request failed") from exc

        if response.is_success:
            try:
                body = response.json()
            except ValueError as exc:
                raise ApiUnavailableError("api returned a non-JSON success response") from exc
            if isinstance(body, dict):
                return body
            raise ApiUnavailableError("api returned an unexpected success response")

        raise ApiClientError(response.status_code, _parse_error_body(response))


def _parse_error_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {
            "code": "api_error",
            "message": response.text or "api request failed",
        }
    if isinstance(body, dict):
        return body
    return {
        "code": "api_error",
        "message": "api request failed",
    }
