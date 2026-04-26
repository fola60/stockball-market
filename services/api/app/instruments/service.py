from __future__ import annotations

from uuid import UUID

from app.instruments.models import InstrumentRecord, PriceSnapshotRecord
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

    def list_price_history(self, instrument_id: UUID) -> list[PriceSnapshotRecord]:
        self.get_instrument(instrument_id)
        return self._repository.list_price_history(instrument_id)
