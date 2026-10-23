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
    # Price protection: the most a buy may cost, or the least a sale must pay, fee included.
    cash_limit: str | None = None


@dataclass(frozen=True)
class QuoteOrderCommand:
    """A quote sized by shares or by cash; exactly one of the two is set."""

    account_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    side: OrderSide
    quantity: str | None = None
    cash_amount: str | None = None
    request_id: str | None = None

    def to_payload(self) -> dict[str, str]:
        payload = {
            "request_id": self.request_id or "",
            "account_id": str(self.account_id),
            "portfolio_id": str(self.portfolio_id),
            "instrument_id": str(self.instrument_id),
            "side": self.side.value,
        }
        if self.quantity is not None:
            payload["quantity"] = self.quantity
        if self.cash_amount is not None:
            payload["cash_amount"] = self.cash_amount
        return payload


@dataclass(frozen=True)
class ExecuteOrderCommand:
    request_id: str
    account_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    side: OrderSide
    quantity: str
    cash_limit: str | None = None

    def to_payload(self) -> dict[str, str]:
        payload = {
            "request_id": self.request_id,
            "account_id": str(self.account_id),
            "portfolio_id": str(self.portfolio_id),
            "instrument_id": str(self.instrument_id),
            "side": self.side.value,
            "quantity": self.quantity,
        }
        if self.cash_limit is not None:
            payload["cash_limit"] = self.cash_limit
        return payload


def _cash_amount(payload: Mapping[str, Any]) -> str:
    """The cash an order moves; engines that predate fees report only the gross amount."""
    return str(payload.get("cash_amount") or payload["gross_amount"])


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
    fee_amount: str = "0"
    # The cash the order moved, fee included; defaults to the gross amount.
    cash_amount: str = ""

    def __post_init__(self) -> None:
        if not self.cash_amount:
            object.__setattr__(self, "cash_amount", self.gross_amount)

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
            fee_amount=str(payload.get("fee_amount") or "0"),
            cash_amount=_cash_amount(payload),
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
    fee_amount: str = "0"
    # The cash the order would move, fee included; defaults to the gross amount.
    cash_amount: str = ""

    def __post_init__(self) -> None:
        if not self.cash_amount:
            object.__setattr__(self, "cash_amount", self.gross_amount)

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
            fee_amount=str(payload.get("fee_amount") or "0"),
            cash_amount=_cash_amount(payload),
            cash_balance_after=str(payload["cash_balance_after"]),
            position_quantity_after=str(payload["position_quantity_after"]),
            old_price=str(payload["old_price"]),
            new_price=str(payload["new_price"]),
            quoted_at=datetime.fromisoformat(str(payload["quoted_at"])),
        )
