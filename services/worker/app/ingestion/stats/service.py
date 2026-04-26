from __future__ import annotations

from typing import Protocol

from .models import ApiFootballPlayerStat, FixturePlayerStatsIngestionResult


class FixturePlayerStatsProviderClient(Protocol):
    def list_fixture_player_stats(self, fixture_id: int) -> list[ApiFootballPlayerStat]: ...


class PlayerStatsRepository(Protocol):
    def upsert_player_stats(self, observations: list[ApiFootballPlayerStat]) -> tuple[int, int]: ...


class FixturePlayerStatsIngestionService:
    def __init__(
        self,
        client: FixturePlayerStatsProviderClient,
        repository: PlayerStatsRepository,
    ) -> None:
        self._client = client
        self._repository = repository

    def ingest_fixture_player_stats(self, fixture_id: int) -> FixturePlayerStatsIngestionResult:
        observations = self._client.list_fixture_player_stats(fixture_id)
        upserted, matched_players = self._repository.upsert_player_stats(observations)
        return FixturePlayerStatsIngestionResult(
            fetched_observations=len(observations),
            upserted_observations=upserted,
            matched_players=matched_players,
        )
