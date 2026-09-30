from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.traders.models import (
    LeaderboardPage,
    TraderKind,
    TraderProfileRecord,
)


class TraderStandingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    display_name: str
    kind: TraderKind
    rank: int
    net_worth: str
    cash_balance: str
    holdings_value: str
    holdings_count: int
    joined_at: datetime


class LeaderboardResponse(BaseModel):
    entries: list[TraderStandingResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_record(cls, page: LeaderboardPage) -> "LeaderboardResponse":
        return cls(
            entries=[TraderStandingResponse.model_validate(item) for item in page.entries],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class TraderHoldingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: UUID
    symbol: str
    player_name: str
    player_club: str | None
    player_position: str | None
    quantity: str
    current_price: str
    market_value: str
    price_change_24h: str


class TraderTradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_id: UUID
    instrument_id: UUID
    player_name: str
    side: str
    shares: str
    execution_price: str
    gross_amount: str
    executed_at: datetime


class TraderProfileResponse(BaseModel):
    trader: TraderStandingResponse
    holdings: list[TraderHoldingResponse]
    recent_trades: list[TraderTradeResponse]

    @classmethod
    def from_record(cls, profile: TraderProfileRecord) -> "TraderProfileResponse":
        return cls(
            trader=TraderStandingResponse.model_validate(profile.standing),
            holdings=[TraderHoldingResponse.model_validate(item) for item in profile.holdings],
            recent_trades=[
                TraderTradeResponse.model_validate(item) for item in profile.recent_trades
            ],
        )
