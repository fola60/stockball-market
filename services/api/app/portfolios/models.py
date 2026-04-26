from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class PositionRecord:
    id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    quantity: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PortfolioRecord:
    id: UUID
    account_id: UUID
    cash_balance: str
    created_at: datetime
    updated_at: datetime
    positions: list[PositionRecord]
