from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.orders.models import OrderExecutionRecord, OrderQuoteRecord, OrderSide

POSITIVE_DECIMAL_PATTERN = re.compile(r"^(?!(?:0(?:\.0+)?)$)(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def _positive_decimal(value: str, places: int) -> str:
    normalized = value.strip()
    if not POSITIVE_DECIMAL_PATTERN.fullmatch(normalized):
        raise ValueError("must be a positive decimal string")

    decimal_value = Decimal(normalized)
    exponent = decimal_value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        raise ValueError(f"supports at most {places} decimal places")

    return format(decimal_value, "f")


def _request_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("must not be empty")
    return normalized


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str | None = Field(default=None, max_length=255)
    instrument_id: UUID
    side: OrderSide
    quantity: str
    # Price protection from the quote: the most a buy may cost, or the least a sale must pay
    # out, fee included. The order is refused if the market has moved past it.
    cash_limit: str | None = None

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str | None) -> str | None:
        return _request_id(value)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: str) -> str:
        return _positive_decimal(value, 6)

    @field_validator("cash_limit")
    @classmethod
    def validate_cash_limit(cls, value: str | None) -> str | None:
        return None if value is None else _positive_decimal(value, 12)


class QuoteOrderRequest(BaseModel):
    """A quote sized by shares (`quantity`) or by cash (`cash_amount`), but not both.

    A cash-sized buy quotes the most shares the amount buys, fee included; a cash-sized sale
    quotes the fewest shares that pay out the amount after the fee, up to the whole position.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = Field(default=None, max_length=255)
    instrument_id: UUID
    side: OrderSide
    quantity: str | None = None
    cash_amount: str | None = None

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str | None) -> str | None:
        return _request_id(value)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: str | None) -> str | None:
        return None if value is None else _positive_decimal(value, 6)

    @field_validator("cash_amount")
    @classmethod
    def validate_cash_amount(cls, value: str | None) -> str | None:
        return None if value is None else _positive_decimal(value, 4)

    @model_validator(mode="after")
    def exactly_one_size(self) -> "QuoteOrderRequest":
        if (self.quantity is None) == (self.cash_amount is None):
            raise ValueError("give exactly one of quantity and cash_amount")
        return self


class OrderExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    fee_amount: str
    cash_amount: str
    cash_balance_after: str
    position_quantity_after: str
    old_price: str
    new_price: str
    executed_at: datetime

    @classmethod
    def from_record(cls, record: OrderExecutionRecord) -> "OrderExecutionResponse":
        return cls.model_validate(record)


class OrderQuoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    side: OrderSide
    quantity: str
    execution_price: str
    gross_amount: str
    fee_amount: str
    cash_amount: str
    cash_balance_after: str
    position_quantity_after: str
    old_price: str
    new_price: str
    quoted_at: datetime

    @classmethod
    def from_record(cls, record: OrderQuoteRecord) -> "OrderQuoteResponse":
        return cls.model_validate(record)
