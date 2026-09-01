from __future__ import annotations

from typing import Protocol

from .models import BettingMarketIngestionResult, BettingMarketObservation


class BettingMarketClient(Protocol):
    def list_pre_match_1x2(self, league: str | None = None) -> list[BettingMarketObservation]: ...


class BettingMarketRepository(Protocol):
    def upsert_observations(self, observations: list[BettingMarketObservation]) -> int: ...


class BettingMarketIngestionService:
    def __init__(self, client: BettingMarketClient, repository: BettingMarketRepository) -> None:
        self._client = client
        self._repository = repository

    def ingest_pre_match_1x2(self, league: str | None = None) -> BettingMarketIngestionResult:
        observations = self._client.list_pre_match_1x2(league)
        return BettingMarketIngestionResult(
            fetched_observations=len(observations),
            upserted_observations=self._repository.upsert_observations(observations),
        )
