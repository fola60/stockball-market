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
class InstrumentFreezeRecord:
    """Why an instrument is frozen. Match-day freezes carry the fixture that caused them."""

    reason: str
    started_at: datetime
    fixture_home_team: str | None = None
    fixture_away_team: str | None = None
    fixture_kickoff_at: datetime | None = None


@dataclass(frozen=True)
class InstrumentRecord:
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
    freeze: InstrumentFreezeRecord | None = None


@dataclass(frozen=True)
class PriceSnapshotRecord:
    id: UUID
    instrument_id: UUID
    old_price: str
    new_price: str
    reason: PriceSnapshotReason
    trade_id: UUID | None
    captured_at: datetime


@dataclass(frozen=True)
class RadarMetricRecord:
    label: str
    score: int
    value: str


@dataclass(frozen=True)
class RadarAxisRecord:
    label: str
    score: int
    value: str
    components: list[RadarMetricRecord]


@dataclass(frozen=True)
class PlayerStatsRecord:
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
    radar_axes: list[RadarAxisRecord]
