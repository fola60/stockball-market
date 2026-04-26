from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.orders.models import ExecuteOrderCommand, OrderExecutionRecord


class TradingEngineClient(Protocol):
    def execute_order(self, command: ExecuteOrderCommand) -> OrderExecutionRecord: ...


class TradingEngineClientError(Exception):
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(body.get("message", "trading engine request failed"))


class TradingEngineUnavailableError(Exception):
    pass


class HttpTradingEngineClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def execute_order(self, command: ExecuteOrderCommand) -> OrderExecutionRecord:
        try:
            response = httpx.post(
                f"{self._base_url}/internal/v1/orders/execute",
                json=command.to_payload(),
                timeout=self._timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise TradingEngineUnavailableError("trading engine request failed") from exc

        if response.is_success:
            return OrderExecutionRecord.from_payload(response.json())

        raise TradingEngineClientError(response.status_code, _parse_error_body(response))


def _parse_error_body(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {
            "code": "trading_engine_error",
            "message": "trading engine returned a non-JSON error response",
            "details": {"body": response.text},
        }

    if isinstance(payload, dict) and "code" in payload and "message" in payload:
        return payload

    return {
        "code": "trading_engine_error",
        "message": "trading engine returned an unexpected error response",
        "details": {"body": payload},
    }
