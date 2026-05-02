from __future__ import annotations

from datetime import date
from typing import Sequence

from app.ingestion.fixtures import FixtureIngestionResult, FixtureIngestionService
from app.ingestion.players import PlayerSeedResult, PlayerSeedService
from app.ingestion.stats import PlayerStatsIngestionResult, PlayerStatsIngestionService


class FbrefIngestionService:
    def __init__(
        self,
        player_seed_service: PlayerSeedService,
        fixture_ingestion_service: FixtureIngestionService,
        player_stats_ingestion_service: PlayerStatsIngestionService,
    ) -> None:
        self._player_seed_service = player_seed_service
        self._fixture_ingestion_service = fixture_ingestion_service
        self._player_stats_ingestion_service = player_stats_ingestion_service

    def seed_players(self, league: int, season: int) -> PlayerSeedResult:
        return self._player_seed_service.seed_players(league, season)

    def ingest_fixtures(
        self,
        league: int,
        season: int,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> FixtureIngestionResult:
        return self._fixture_ingestion_service.ingest_fixtures(
            league=league,
            season=season,
            from_date=from_date,
            to_date=to_date,
        )

    def ingest_player_stats(
        self,
        league: int,
        season: int,
        stat_types: Sequence[str] | None = None,
    ) -> PlayerStatsIngestionResult:
        return self._player_stats_ingestion_service.ingest_player_stats(
            league=league,
            season=season,
            stat_types=stat_types,
        )
