from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import (
    Bet365DiscoveredFixture,
    BettingMarketIngestionResult,
    BettingMarketObservation,
)

DEFAULT_LIVE_EVENT_WINDOW_MINUTES = 180
DEFAULT_LIVE_EVENT_LIMIT = 20


class BettingMarketClient(Protocol):
    def list_pre_match_markets(
        self,
        league: str | None = None,
    ) -> list[BettingMarketObservation]: ...

    def list_live_markets(
        self,
        fixtures: tuple[Bet365DiscoveredFixture, ...],
    ) -> list[BettingMarketObservation]: ...


class BettingMarketRepository(Protocol):
    def upsert_observations(self, observations: list[BettingMarketObservation]) -> int: ...

    def list_live_event_pages(
        self,
        as_of: datetime,
        *,
        event_window_minutes: int,
        limit: int,
    ) -> tuple[Bet365DiscoveredFixture, ...]: ...


class BettingMarketIngestionService:
    def __init__(
        self,
        client: BettingMarketClient,
        repository: BettingMarketRepository,
        *,
        live_event_window_minutes: int = DEFAULT_LIVE_EVENT_WINDOW_MINUTES,
        live_event_limit: int = DEFAULT_LIVE_EVENT_LIMIT,
    ) -> None:
        if live_event_window_minutes <= 0:
            raise ValueError("live_event_window_minutes must be greater than 0")
        if live_event_limit <= 0:
            raise ValueError("live_event_limit must be greater than 0")
        self._client = client
        self._repository = repository
        self._live_event_window_minutes = live_event_window_minutes
        self._live_event_limit = live_event_limit

    def ingest_pre_match_markets(
        self,
        league: str | None = None,
    ) -> BettingMarketIngestionResult:
        observations = self._client.list_pre_match_markets(league)
        return BettingMarketIngestionResult(
            fetched_observations=len(observations),
            upserted_observations=self._repository.upsert_observations(observations),
        )

    def ingest_live_markets(self, as_of: datetime) -> BettingMarketIngestionResult:
        fixtures = self._repository.list_live_event_pages(
            as_of,
            event_window_minutes=self._live_event_window_minutes,
            limit=self._live_event_limit,
        )
        observations = self._client.list_live_markets(fixtures) if fixtures else []
        return BettingMarketIngestionResult(
            fetched_observations=len(observations),
            upserted_observations=self._repository.upsert_observations(observations),
        )
