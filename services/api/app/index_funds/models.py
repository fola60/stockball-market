from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.instruments.models import InstrumentStatus, RadarAxisRecord


@dataclass(frozen=True)
class IndexFundRecord:
    id: UUID
    symbol: str
    display_name: str
    index_kind: str
    club: str | None
    # The value of one unit: its basket at current prices plus its cash.
    current_price: str
    # Cash behind each unit, from buyouts of players who left the league, until the next
    # rebalance spends it.
    cash_per_unit: str
    # FROZEN while the fund or any constituent cannot trade, since a unit trades as a whole.
    status: InstrumentStatus
    # Why a constituent is frozen, MATCH_DAY first when any is paused for a match.
    freeze_reason: str | None
    constituent_count: int
    units_outstanding: str
    price_change_24h: str
    price_change_7d: str
    volume_24h: str
    traded_value_24h: str
    club_badge_version: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class IndexConstituentRecord:
    instrument_id: UUID
    symbol: str
    player_name: str
    player_position: str | None
    status: InstrumentStatus
    shares_per_unit: str
    current_price: str
    # Share of one unit's value, in percent.
    weight: str
    price_change_24h: str
    player_image_version: str | None


@dataclass(frozen=True)
class IndexFundProfileRecord:
    """The squad's radar: each axis is its players' percentile, weighted by unit value.

    Players are ranked against their own position, so a keeper's shot stopping and a
    striker's finishing both mean "how good for their role". Axes only some positions have,
    like shot stopping, average over the players who have them.
    """

    comparison_group: str
    comparison_size: int
    radar_axes: list[RadarAxisRecord]


@dataclass(frozen=True)
class BasketChangePlayerRecord:
    instrument_id: UUID
    player_name: str


@dataclass(frozen=True)
class BasketChangeRecord:
    """A rebalance to the fund's rule, or a player bought out after leaving the league."""

    kind: str
    reason: str
    added: list[BasketChangePlayerRecord]
    removed: list[BasketChangePlayerRecord]
    unit_price_before: str
    unit_price_after: str
    created_at: datetime


@dataclass(frozen=True)
class IndexFundDetailRecord:
    fund: IndexFundRecord
    constituents: list[IndexConstituentRecord]
    profile: IndexFundProfileRecord | None
    basket_changes: list[BasketChangeRecord]
