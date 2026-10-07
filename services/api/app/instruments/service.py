from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from app.instruments.models import (
    ImageRecord,
    InstrumentRecord,
    PlayerStatsRecord,
    PriceSnapshotRecord,
)
from app.instruments.repository import InstrumentsRepository


class InstrumentNotFoundError(Exception):
    def __init__(self, instrument_id: UUID) -> None:
        self.instrument_id = instrument_id
        super().__init__(f"instrument {instrument_id} was not found")


class InstrumentsService:
    def __init__(self, repository: InstrumentsRepository) -> None:
        self._repository = repository

    def list_instruments(self) -> list[InstrumentRecord]:
        return self._repository.list_instruments()

    def get_instrument(self, instrument_id: UUID) -> InstrumentRecord:
        instrument = self._repository.get_instrument(instrument_id)
        if instrument is None:
            raise InstrumentNotFoundError(instrument_id)
        return instrument

    def list_price_history(
        self,
        instrument_id: UUID,
        history_range: Literal["1D", "1W", "1M", "3M", "1Y", "ALL"] = "ALL",
    ) -> list[PriceSnapshotRecord]:
        self.get_instrument(instrument_id)
        durations = {
            "1D": timedelta(days=1),
            "1W": timedelta(weeks=1),
            "1M": timedelta(days=30),
            "3M": timedelta(days=90),
            "1Y": timedelta(days=365),
        }
        duration = durations.get(history_range)
        since = datetime.now(UTC) - duration if duration is not None else None
        return self._repository.list_price_history(instrument_id, since)

    def get_player_stats(self, instrument_id: UUID) -> PlayerStatsRecord | None:
        self.get_instrument(instrument_id)
        return self._repository.get_player_stats(instrument_id)

    def get_player_image(self, instrument_id: UUID) -> ImageRecord | None:
        return self._repository.get_player_image(instrument_id)

    def get_club_badge(self, instrument_id: UUID) -> ImageRecord | None:
        return self._repository.get_club_badge(instrument_id)
