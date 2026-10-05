from __future__ import annotations

from typing import Protocol, Sequence

from .models import ExternalPlayerStat, PlayerStatsIngestionResult


class PlayerStatsProviderClient(Protocol):
    def list_player_stats(
        self,
        league: int,
        season: int,
        stat_types: Sequence[str] | None = None,
    ) -> list[ExternalPlayerStat]: ...


class PlayerStatsRepository(Protocol):
    def upsert_player_stats(self, observations: list[ExternalPlayerStat]) -> tuple[int, int]: ...

    def record_season_snapshots(self, provider: str, season: int) -> int: ...


class PlayerStatsIngestionService:
    def __init__(
        self,
        client: PlayerStatsProviderClient,
        repository: PlayerStatsRepository,
    ) -> None:
        self._client = client
        self._repository = repository

    def ingest_player_stats(
        self,
        league: int,
        season: int,
        stat_types: Sequence[str] | None = None,
    ) -> PlayerStatsIngestionResult:
        observations = self._client.list_player_stats(league, season, stat_types)
        upserted, matched_players = self._repository.upsert_player_stats(observations)
        snapshots = 0
        if observations:
            # Keep a dated copy of the season totals so form can be measured between days.
            snapshots = self._repository.record_season_snapshots(
                observations[0].provider, season
            )
        return PlayerStatsIngestionResult(
            fetched_observations=len(observations),
            upserted_observations=upserted,
            matched_players=matched_players,
            snapshots_recorded=snapshots,
        )
