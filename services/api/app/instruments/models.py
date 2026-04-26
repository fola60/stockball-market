from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class InstrumentType(StrEnum):
    PLAYER_SHARE = "PLAYER_SHARE"


class InstrumentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    DELISTED = "DELISTED"


class PriceSnapshotReason(StrEnum):
    SEED = "SEED"
    TRADE_BUY = "TRADE_BUY"
    TRADE_SELL = "TRADE_SELL"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"


@dataclass(frozen=True)
class InstrumentRecord:
    id: UUID
    instrument_type: InstrumentType
    player_id: UUID
    symbol: str
    display_name: str
    current_price: str
    quantity_outstanding: str
    price_impact_unit: str
    status: InstrumentStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PriceSnapshotRecord:
    id: UUID
    instrument_id: UUID
    old_price: str
    new_price: str
    reason: PriceSnapshotReason
    trade_id: UUID | None
    captured_at: datetime
