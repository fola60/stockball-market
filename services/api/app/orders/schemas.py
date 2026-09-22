from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.orders.models import OrderExecutionRecord, OrderQuoteRecord, OrderSide

POSITIVE_DECIMAL_PATTERN = re.compile(r"^(?!(?:0(?:\.0+)?)$)(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str | None = Field(default=None, max_length=255)
    instrument_id: UUID
    side: OrderSide
    quantity: str

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: str) -> str:
        normalized = value.strip()
        if not POSITIVE_DECIMAL_PATTERN.fullmatch(normalized):
            raise ValueError("must be a positive decimal string")

        decimal_value = Decimal(normalized)
        exponent = decimal_value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -6:
            raise ValueError("supports at most 6 decimal places")

        return format(decimal_value, "f")


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
    cash_balance_after: str
    position_quantity_after: str
    old_price: str
    new_price: str
    quoted_at: datetime

    @classmethod
    def from_record(cls, record: OrderQuoteRecord) -> "OrderQuoteResponse":
        return cls.model_validate(record)
