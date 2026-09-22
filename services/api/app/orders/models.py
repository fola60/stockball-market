from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class SubmitOrderCommand:
    account_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    side: OrderSide
    quantity: str
    request_id: str | None = None


@dataclass(frozen=True)
class ExecuteOrderCommand:
    request_id: str
    account_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    side: OrderSide
    quantity: str

    def to_payload(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "account_id": str(self.account_id),
            "portfolio_id": str(self.portfolio_id),
            "instrument_id": str(self.instrument_id),
            "side": self.side.value,
            "quantity": self.quantity,
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
class OrderQuoteRecord:
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
    quoted_at: datetime

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "OrderQuoteRecord":
        return cls(
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
            quoted_at=datetime.fromisoformat(str(payload["quoted_at"])),
        )
