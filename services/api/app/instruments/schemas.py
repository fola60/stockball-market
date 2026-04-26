from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.instruments.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
    PriceSnapshotReason,
    PriceSnapshotRecord,
)


class InstrumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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

    @classmethod
    def from_record(cls, instrument: InstrumentRecord) -> "InstrumentResponse":
        return cls.model_validate(instrument)


class PriceSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    instrument_id: UUID
    old_price: str
    new_price: str
    reason: PriceSnapshotReason
    trade_id: UUID | None
    captured_at: datetime

    @classmethod
    def from_record(cls, snapshot: PriceSnapshotRecord) -> "PriceSnapshotResponse":
        return cls.model_validate(snapshot)
