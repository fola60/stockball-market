from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.instruments.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
    PlayerStatsRecord,
    PriceSnapshotReason,
    PriceSnapshotRecord,
    RadarAxisRecord,
)


class InstrumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    instrument_type: InstrumentType
    player_id: UUID
    symbol: str
    display_name: str
    current_price: str
    reference_price: str
    quantity_outstanding: str
    net_shares_purchased: str
    full_supply_price_multiplier: str
    status: InstrumentStatus
    created_at: datetime
    updated_at: datetime
    player_name: str | None = None
    player_club: str | None = None
    player_position: str | None = None
    price_change_24h: str = "0.0000"
    volume_24h: str = "0.000000"

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


class RadarAxisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    score: int
    value: str

    @classmethod
    def from_record(cls, axis: RadarAxisRecord) -> "RadarAxisResponse":
        return cls.model_validate(axis)


class PlayerStatsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    season: int | None
    games: int
    starts: int
    minutes: int
    goals: int
    assists: int
    shots: int
    shots_on_target: int
    yellow_cards: int
    red_cards: int
    comparison_group: str
    comparison_size: int
    radar_axes: list[RadarAxisResponse]

    @classmethod
    def from_record(cls, stats: PlayerStatsRecord) -> "PlayerStatsResponse":
        return cls.model_validate(stats)
