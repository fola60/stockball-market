from __future__ import annotations

from datetime import date
from typing import Protocol

from .models import ExternalFixture, FixtureIngestionResult


class FixtureProviderClient(Protocol):
    def list_fixtures(
        self,
        league: int,
        season: int,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ExternalFixture]: ...


class FixtureRepository(Protocol):
    def upsert_fixtures(self, fixtures: list[ExternalFixture]) -> int: ...


class FixtureIngestionService:
    def __init__(self, client: FixtureProviderClient, repository: FixtureRepository) -> None:
        self._client = client
        self._repository = repository

    def ingest_fixtures(
        self,
        league: int,
        season: int,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> FixtureIngestionResult:
        fixtures = self._client.list_fixtures(league, season, from_date, to_date)
        upserted = self._repository.upsert_fixtures(fixtures)
        return FixtureIngestionResult(
            fetched_fixtures=len(fixtures),
            upserted_fixtures=upserted,
        )
