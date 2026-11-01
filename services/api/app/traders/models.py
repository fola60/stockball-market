from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TraderKind(StrEnum):
    PERSON = "PERSON"
    BOT = "BOT"


class LeaderboardFilter(StrEnum):
    ALL = "ALL"
    PEOPLE = "PEOPLE"
    BOTS = "BOTS"


@dataclass(frozen=True)
class TraderStandingRecord:
    account_id: UUID
    display_name: str
    kind: TraderKind
    rank: int
    net_worth: str
    cash_balance: str
    holdings_value: str
    holdings_count: int
    joined_at: datetime
    day_change: str = "0.0000"
    day_change_percent: str = "0.0000"
    # Capital the trader was given, net worth less that, and the return as a percentage of it.
    # The return is None for an account that was given nothing.
    contributed_capital: str = "0.0000"
    total_return: str = "0.0000"
    return_percent: str | None = None


@dataclass(frozen=True)
class LeaderboardPage:
    entries: list[TraderStandingRecord]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class TraderHoldingRecord:
    instrument_id: UUID
    symbol: str
    player_name: str
    player_club: str | None
    player_position: str | None
    quantity: str
    current_price: str
    market_value: str
    price_change_24h: str


@dataclass(frozen=True)
class TraderTradeRecord:
    trade_id: UUID
    instrument_id: UUID
    player_name: str
    side: str
    shares: str
    execution_price: str
    gross_amount: str
    executed_at: datetime
    fee_amount: str = "0.0000"


@dataclass(frozen=True)
class TraderProfileRecord:
    standing: TraderStandingRecord
    holdings: list[TraderHoldingRecord]
    recent_trades: list[TraderTradeRecord]
