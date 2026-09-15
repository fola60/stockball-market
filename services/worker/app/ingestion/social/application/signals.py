from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol


class SocialSignalRepository(Protocol):
    def calculate_signal_snapshots(self, calculated_at: datetime, lookback: timedelta) -> int: ...


@dataclass(frozen=True)
class SocialSignalAggregationResult:
    calculated_at: datetime
    lookback: timedelta
    snapshots_written: int


class SocialSignalAggregationService:
    def __init__(
        self,
        repository: SocialSignalRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._clock = clock

    def aggregate(self, lookback: timedelta) -> SocialSignalAggregationResult:
        if lookback <= timedelta():
            raise ValueError("social signal lookback must be positive")
        calculated_at = self._clock()
        written = self._repository.calculate_signal_snapshots(calculated_at, lookback)
        return SocialSignalAggregationResult(calculated_at, lookback, written)

