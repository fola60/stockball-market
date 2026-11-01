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
    # What the shares still held cost, fees included, and the profit their sales locked in.
    cost_basis: str = "0"
    realized_pnl: str = "0"


@dataclass(frozen=True)
class PortfolioRecord:
    id: UUID
    account_id: UUID
    cash_balance: str
    created_at: datetime
    updated_at: datetime
    positions: list[PositionRecord]
    # The capital the portfolio was given (opening balance, top-ups, issued shares) and the
    # profit locked in by every sale, including positions since closed.
    contributed_capital: str = "0"
    realized_pnl: str = "0"


@dataclass(frozen=True)
class PortfolioActivityRecord:
    id: UUID
    instrument_id: UUID
    symbol: str
    player_name: str
    side: str
    shares: str
    execution_price: str
    gross_amount: str
    executed_at: datetime
    fee_amount: str = "0"
