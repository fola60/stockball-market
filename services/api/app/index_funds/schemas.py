from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.index_funds.models import IndexFundDetailRecord, IndexFundRecord
from app.instruments.models import InstrumentStatus
from app.instruments.schemas import RadarAxisResponse


class IndexFundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    symbol: str
    display_name: str
    index_kind: str
    club: str | None
    current_price: str
    cash_per_unit: str
    status: InstrumentStatus
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

    @classmethod
    def from_record(cls, record: IndexFundRecord) -> "IndexFundResponse":
        return cls.model_validate(record)


class IndexConstituentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: UUID
    symbol: str
    player_name: str
    player_position: str | None
    status: InstrumentStatus
    shares_per_unit: str
    current_price: str
    weight: str
    price_change_24h: str
    player_image_version: str | None


class IndexFundProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    comparison_group: str
    comparison_size: int
    radar_axes: list[RadarAxisResponse]


class BasketChangePlayerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: UUID
    player_name: str


class BasketChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    reason: str
    added: list[BasketChangePlayerResponse]
    removed: list[BasketChangePlayerResponse]
    unit_price_before: str
    unit_price_after: str
    created_at: datetime


class IndexFundDetailResponse(IndexFundResponse):
    constituents: list[IndexConstituentResponse]
    profile: IndexFundProfileResponse | None
    basket_changes: list[BasketChangeResponse]

    @classmethod
    def from_detail(cls, detail: IndexFundDetailRecord) -> "IndexFundDetailResponse":
        return cls.model_validate(
            {
                **IndexFundResponse.from_record(detail.fund).model_dump(),
                "constituents": [
                    IndexConstituentResponse.model_validate(constituent)
                    for constituent in detail.constituents
                ],
                "profile": None
                if detail.profile is None
                else IndexFundProfileResponse.model_validate(detail.profile),
                "basket_changes": [
                    BasketChangeResponse.model_validate(change)
                    for change in detail.basket_changes
                ],
            }
        )
