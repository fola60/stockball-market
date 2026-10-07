from __future__ import annotations

import atexit
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Protocol
from uuid import UUID

import httpx


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class LedgerReason(StrEnum):
    WEEKLY_TOPUP = "WEEKLY_TOPUP"
    MONTHLY_TOPUP = "MONTHLY_TOPUP"


@dataclass(frozen=True)
class TradingEngineEndpoints:
    quote_order: str = "/internal/v1/orders/quote"
    execute_order: str = "/internal/v1/orders/execute"
    seed_player_shares: str = "/internal/v1/instruments/player-shares/seed"
    apply_topup: str = "/internal/v1/ledger/topups/apply"
    issue_initial_supply: str = "/internal/v1/positions/initial-supply/issue"
    set_pre_market_price: str = "/internal/v1/instruments/pre-market-price/set"
    recalibrate_price_curves: str = "/internal/v1/instruments/price-curves/recalibrate"
    apply_freeze: str = "/internal/v1/freezes/apply"
    release_freeze: str = "/internal/v1/freezes/release"


@dataclass(frozen=True)
class ExecuteOrderCommand:
    request_id: str
    account_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    side: OrderSide
    quantity: str
    execution_limits: Mapping[str, str] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "account_id": str(self.account_id),
            "portfolio_id": str(self.portfolio_id),
            "instrument_id": str(self.instrument_id),
            "side": self.side.value,
            "quantity": self.quantity,
            **(
                {"execution_limits": dict(self.execution_limits)}
                if self.execution_limits is not None
                else {}
            ),
        }


@dataclass(frozen=True)
class OrderExecutionRecord:
    request_id: str
    order_id: UUID
    trade_id: UUID
    account_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    side: OrderSide
    quantity: str
    execution_price: str
    gross_amount: str
    cash_balance_after: str
    position_quantity_after: str
    old_price: str
    new_price: str
    executed_at: datetime

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "OrderExecutionRecord":
        return cls(
            request_id=str(payload["request_id"]),
            order_id=UUID(str(payload["order_id"])),
            trade_id=UUID(str(payload["trade_id"])),
            account_id=UUID(str(payload["account_id"])),
            portfolio_id=UUID(str(payload["portfolio_id"])),
            instrument_id=UUID(str(payload["instrument_id"])),
            side=OrderSide(str(payload["side"])),
            quantity=str(payload["quantity"]),
            execution_price=str(payload["execution_price"]),
            gross_amount=str(payload["gross_amount"]),
            cash_balance_after=str(payload["cash_balance_after"]),
            position_quantity_after=str(payload["position_quantity_after"]),
            old_price=str(payload["old_price"]),
            new_price=str(payload["new_price"]),
            executed_at=datetime.fromisoformat(str(payload["executed_at"])),
        )


@dataclass(frozen=True)
class ApplyTopupCommand:
    request_id: str
    account_id: UUID
    portfolio_id: UUID
    amount: str
    reason: LedgerReason

    def to_payload(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "account_id": str(self.account_id),
            "portfolio_id": str(self.portfolio_id),
            "amount": self.amount,
            "reason": self.reason.value,
        }


@dataclass(frozen=True)
class CashLedgerEntryRecord:
    id: UUID
    account_id: UUID
    portfolio_id: UUID
    trade_id: UUID | None
    reason: LedgerReason
    amount_delta: str
    balance_after: str
    source_request_id: str | None
    created_at: datetime

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "CashLedgerEntryRecord":
        trade_id = payload.get("trade_id")
        return cls(
            id=UUID(str(payload["id"])),
            account_id=UUID(str(payload["account_id"])),
            portfolio_id=UUID(str(payload["portfolio_id"])),
            trade_id=None if trade_id is None else UUID(str(trade_id)),
            reason=LedgerReason(str(payload["reason"])),
            amount_delta=str(payload["amount_delta"]),
            balance_after=str(payload["balance_after"]),
            source_request_id=_optional_string(payload.get("source_request_id")),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
        )


@dataclass(frozen=True)
class SeedPlayerSharesRecord:
    created_count: int
    skipped_existing_count: int
    market_value_priced_count: int
    fallback_priced_count: int
    created_instrument_ids: tuple[UUID, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SeedPlayerSharesRecord":
        return cls(
            created_count=int(payload["created_count"]),
            skipped_existing_count=int(payload["skipped_existing_count"]),
            market_value_priced_count=int(payload["market_value_priced_count"]),
            fallback_priced_count=int(payload["fallback_priced_count"]),
            created_instrument_ids=tuple(
                UUID(str(instrument_id)) for instrument_id in payload["created_instrument_ids"]
            ),
        )


@dataclass(frozen=True)
class InitialSupplyAllocation:
    instrument_id: UUID
    portfolio_id: UUID
    quantity: str


@dataclass(frozen=True)
class IssueInitialSupplyCommand:
    request_id: str
    allocations: tuple[InitialSupplyAllocation, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "allocations": [
                {
                    "instrument_id": str(item.instrument_id),
                    "portfolio_id": str(item.portfolio_id),
                    "quantity": item.quantity,
                }
                for item in self.allocations
            ],
        }


@dataclass(frozen=True)
class SetPreMarketPriceCommand:
    request_id: str
    instrument_id: UUID
    new_price: str

    def to_payload(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "instrument_id": str(self.instrument_id),
            "new_price": self.new_price,
        }


@dataclass(frozen=True)
class PreMarketPriceRecord:
    instrument_id: UUID
    old_price: str
    new_price: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "PreMarketPriceRecord":
        return cls(
            instrument_id=UUID(str(payload["instrument_id"])),
            old_price=str(payload["old_price"]),
            new_price=str(payload["new_price"]),
        )


@dataclass(frozen=True)
class RecalibratePriceCurvesCommand:
    """Re-anchors every player-share curve at its current price with a new shape: net buying of
    shares_outstanding ÷ curve_depth_divisor reaches full_supply_price_multiplier times the
    reference. No price changes; only how far later trades move prices."""

    request_id: str
    full_supply_price_multiplier: str
    curve_depth_divisor: str
    reason: str
    dry_run: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "full_supply_price_multiplier": self.full_supply_price_multiplier,
            "curve_depth_divisor": self.curve_depth_divisor,
            "reason": self.reason,
            "dry_run": self.dry_run,
        }


@dataclass(frozen=True)
class RecalibratePriceCurvesRecord:
    request_id: str
    dry_run: bool
    full_supply_price_multiplier: str
    curve_depth_divisor: str
    instrument_count: int
    reset_net_demand_count: int
    max_reset_demand_ratio: str
    previous_min_multiplier: str | None
    previous_max_multiplier: str | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "RecalibratePriceCurvesRecord":
        return cls(
            request_id=str(payload["request_id"]),
            dry_run=bool(payload["dry_run"]),
            full_supply_price_multiplier=str(payload["full_supply_price_multiplier"]),
            curve_depth_divisor=str(payload["curve_depth_divisor"]),
            instrument_count=int(payload["instrument_count"]),
            reset_net_demand_count=int(payload["reset_net_demand_count"]),
            max_reset_demand_ratio=str(payload["max_reset_demand_ratio"]),
            previous_min_multiplier=_optional_str(payload.get("previous_min_multiplier")),
            previous_max_multiplier=_optional_str(payload.get("previous_max_multiplier")),
        )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class ApplyFreezeCommand:
    reason: str
    source_key: str
    instrument_ids: tuple[UUID, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "source_key": self.source_key,
            "instrument_ids": [str(item) for item in self.instrument_ids],
        }


@dataclass(frozen=True)
class ApplyFreezeRecord:
    source_key: str
    opened_count: int
    already_open_count: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ApplyFreezeRecord":
        return cls(
            source_key=str(payload["source_key"]),
            opened_count=int(payload["opened_count"]),
            already_open_count=int(payload["already_open_count"]),
        )


@dataclass(frozen=True)
class ReleaseFreezeRecord:
    source_key: str
    released_count: int
    reactivated_instrument_ids: tuple[UUID, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ReleaseFreezeRecord":
        return cls(
            source_key=str(payload["source_key"]),
            released_count=int(payload["released_count"]),
            reactivated_instrument_ids=tuple(
                UUID(str(item)) for item in payload["reactivated_instrument_ids"]
            ),
        )


@dataclass(frozen=True)
class OrderQuoteRecord:
    quantity: str
    gross_amount: str
    cash_balance_after: str
    position_quantity_after: str
    old_price: str
    new_price: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "OrderQuoteRecord":
        return cls(**{name: str(payload[name]) for name in cls.__dataclass_fields__})


class TradingEngineClient(Protocol):
    def quote_order(self, command: ExecuteOrderCommand) -> OrderQuoteRecord: ...

    def execute_order(self, command: ExecuteOrderCommand) -> OrderExecutionRecord: ...

    def seed_player_shares(self) -> SeedPlayerSharesRecord: ...

    def apply_topup(self, command: ApplyTopupCommand) -> CashLedgerEntryRecord: ...


class InitialSupplyIssuer(Protocol):
    def issue_initial_supply(self, command: IssueInitialSupplyCommand) -> None: ...


class PreMarketPricer(Protocol):
    def set_pre_market_price(self, command: SetPreMarketPriceCommand) -> PreMarketPriceRecord: ...


class FreezeClient(Protocol):
    def apply_freeze(self, command: ApplyFreezeCommand) -> ApplyFreezeRecord: ...

    def release_freeze(self, source_key: str) -> ReleaseFreezeRecord: ...


class TradingEngineClientError(Exception):
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(body.get("message", "trading engine request failed"))

    @property
    def retryable(self) -> bool:
        return self.status_code >= 500 or self.status_code in {408, 429}


class TradingEngineUnavailableError(Exception):
    pass


class HttpTradingEngineClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        endpoints: TradingEngineEndpoints | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._endpoints = endpoints or TradingEngineEndpoints()
        self._transport = transport
        self._client = httpx.Client(
            timeout=self._timeout_seconds,
            transport=self._transport,
        )
        atexit.register(self.close)

    def close(self) -> None:
        if not self._client.is_closed:
            self._client.close()

    def quote_order(self, command: ExecuteOrderCommand) -> OrderQuoteRecord:
        return OrderQuoteRecord.from_payload(
            self._post(self._endpoints.quote_order, command.to_payload())
        )

    def execute_order(self, command: ExecuteOrderCommand) -> OrderExecutionRecord:
        payload = self._post(self._endpoints.execute_order, command.to_payload())
        return OrderExecutionRecord.from_payload(payload)

    def seed_player_shares(self) -> SeedPlayerSharesRecord:
        payload = self._post(self._endpoints.seed_player_shares, {})
        return SeedPlayerSharesRecord.from_payload(payload)

    def apply_topup(self, command: ApplyTopupCommand) -> CashLedgerEntryRecord:
        payload = self._post(self._endpoints.apply_topup, command.to_payload())
        return CashLedgerEntryRecord.from_payload(payload)

    def issue_initial_supply(self, command: IssueInitialSupplyCommand) -> None:
        self._post(self._endpoints.issue_initial_supply, command.to_payload())

    def set_pre_market_price(self, command: SetPreMarketPriceCommand) -> PreMarketPriceRecord:
        payload = self._post(self._endpoints.set_pre_market_price, command.to_payload())
        return PreMarketPriceRecord.from_payload(payload)

    def recalibrate_price_curves(
        self, command: RecalibratePriceCurvesCommand
    ) -> RecalibratePriceCurvesRecord:
        payload = self._post(self._endpoints.recalibrate_price_curves, command.to_payload())
        return RecalibratePriceCurvesRecord.from_payload(payload)

    def apply_freeze(self, command: ApplyFreezeCommand) -> ApplyFreezeRecord:
        payload = self._post(self._endpoints.apply_freeze, command.to_payload())
        return ApplyFreezeRecord.from_payload(payload)

    def release_freeze(self, source_key: str) -> ReleaseFreezeRecord:
        payload = self._post(self._endpoints.release_freeze, {"source_key": source_key})
        return ReleaseFreezeRecord.from_payload(payload)

    def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(f"{self._base_url}{path}", json=dict(payload))
        except httpx.HTTPError as exc:
            raise TradingEngineUnavailableError("trading engine request failed") from exc

        if response.is_success:
            try:
                body = response.json()
            except ValueError as exc:
                raise TradingEngineUnavailableError(
                    "trading engine returned a non-JSON success response"
                ) from exc

            if isinstance(body, dict):
                return body

            raise TradingEngineUnavailableError(
                "trading engine returned an unexpected success response"
            )

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


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
