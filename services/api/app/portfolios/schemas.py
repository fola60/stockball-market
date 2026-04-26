from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.portfolios.models import PortfolioRecord, PositionRecord


class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    quantity: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, position: PositionRecord) -> "PositionResponse":
        return cls.model_validate(position)


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    cash_balance: str
    created_at: datetime
    updated_at: datetime
    positions: list[PositionResponse]

    @classmethod
    def from_record(cls, portfolio: PortfolioRecord) -> "PortfolioResponse":
        return cls(
            id=portfolio.id,
            account_id=portfolio.account_id,
            cash_balance=portfolio.cash_balance,
            created_at=portfolio.created_at,
            updated_at=portfolio.updated_at,
            positions=[PositionResponse.from_record(position) for position in portfolio.positions],
        )
