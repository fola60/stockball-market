from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx

from app.ingestion.fixtures import ApiFootballFixture, FixtureIngestionService
from app.ingestion.providers import ApiFootballClient
from app.ingestion.stats import ApiFootballPlayerStat, FixturePlayerStatsIngestionService
from app.jobs import (
    IngestFixturePlayerStatsJobHandler,
    IngestFixturePlayerStatsJobPayload,
    IngestFixturesJobHandler,
    IngestFixturesJobPayload,
    JobType,
    WorkerJob,
)


class FakeFixtureRepository:
    def __init__(self) -> None:
        self.fixtures: list[ApiFootballFixture] = []

    def upsert_fixtures(self, fixtures: list[ApiFootballFixture]) -> int:
        self.fixtures.extend(fixtures)
        return len(fixtures)


class FakeStatsRepository:
    def __init__(self, matched_players: int = 0) -> None:
        self.observations: list[ApiFootballPlayerStat] = []
        self.matched_players = matched_players

    def upsert_player_stats(self, observations: list[ApiFootballPlayerStat]) -> tuple[int, int]:
        self.observations.extend(observations)
        return len(observations), self.matched_players


class FakeApiFootballClient:
    def __init__(
        self,
        fixtures: list[ApiFootballFixture] | None = None,
        stats: list[ApiFootballPlayerStat] | None = None,
    ) -> None:
        self.fixtures = fixtures or []
        self.stats = stats or []
        self.fixture_calls: list[tuple[int, int, date | None, date | None]] = []
        self.stats_calls: list[int] = []

    def list_fixtures(
        self,
        league: int,
        season: int,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ApiFootballFixture]:
        self.fixture_calls.append((league, season, from_date, to_date))
        return self.fixtures

    def list_fixture_player_stats(self, fixture_id: int) -> list[ApiFootballPlayerStat]:
        self.stats_calls.append(fixture_id)
        return self.stats


class ApiFootballClientTests(unittest.TestCase):
    def test_list_fixtures_maps_api_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/fixtures")
            self.assertEqual(request.url.params["league"], "39")
            self.assertEqual(request.url.params["season"], "2025")
            return _json_response(
                {
                    "response": [
                        {
                            "fixture": {
                                "id": 1208040,
                                "date": "2025-08-16T11:30:00+00:00",
                                "status": {"long": "Not Started", "short": "NS", "elapsed": None},
                            },
                            "league": {"id": 39, "season": 2025},
                            "teams": {
                                "home": {"id": 42, "name": "Arsenal"},
                                "away": {"id": 50, "name": "Manchester City"},
                            },
                        }
                    ]
                }
            )

        client = ApiFootballClient(
            api_key="token",
            request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
        )

        fixtures = client.list_fixtures(league=39, season=2025)

        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0].provider, "https://v3.football.api-sports.io")
        self.assertEqual(fixtures[0].provider_fixture_id, "1208040")
        self.assertEqual(fixtures[0].kickoff_at, datetime(2025, 8, 16, 11, 30, tzinfo=UTC))
        self.assertEqual(fixtures[0].home_team_name, "Arsenal")
        self.assertEqual(fixtures[0].status_short, "NS")

    def test_list_fixture_player_stats_maps_ratings(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/fixtures/players")
            self.assertEqual(request.url.params["fixture"], "1208040")
            return _json_response(
                {
                    "response": [
                        {
                            "team": {"id": 42, "name": "Arsenal"},
                            "players": [
                                {
                                    "player": {"id": 1460, "name": "Bukayo Saka"},
                                    "statistics": [
                                        {
                                            "games": {
                                                "minutes": 90,
                                                "position": "F",
                                                "rating": "7.8",
                                            },
                                            "goals": {"total": 1, "assists": 1},
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            )

        client = ApiFootballClient(
            api_key="token",
            request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
        )

        observations = client.list_fixture_player_stats(1208040)

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].provider_player_id, "1460")
        self.assertEqual(observations[0].display_name, "Bukayo Saka")
        self.assertEqual(observations[0].team_name, "Arsenal")
        self.assertEqual(observations[0].rating, Decimal("7.8"))
        self.assertEqual(observations[0].stats["games"]["minutes"], 90)


class ApiFootballServiceTests(unittest.TestCase):
    def test_fixture_handler_ingests_fixtures(self) -> None:
        fixture = _fixture()
        client = FakeApiFootballClient(fixtures=[fixture])
        service = FixtureIngestionService(client=client, repository=FakeFixtureRepository())
        handler = IngestFixturesJobHandler(
            fixture_ingestion_service=service,
            clock=lambda: datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
        )

        result = handler.handle(
            WorkerJob.ingest_fixtures(
                IngestFixturesJobPayload(
                    league=39,
                    season=2025,
                    from_date=date(2025, 8, 16),
                    to_date=date(2025, 8, 17),
                )
            )
        )

        self.assertEqual(result.job_type, JobType.INGEST_FIXTURES)
        self.assertEqual(result.successful_items, 1)
        self.assertEqual(client.fixture_calls[0][0], 39)

    def test_fixture_player_stats_handler_ingests_stats(self) -> None:
        observation = _player_stat()
        client = FakeApiFootballClient(stats=[observation])
        service = FixturePlayerStatsIngestionService(
            client=client,
            repository=FakeStatsRepository(matched_players=0),
        )
        handler = IngestFixturePlayerStatsJobHandler(
            stats_ingestion_service=service,
            clock=lambda: datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
        )

        result = handler.handle(
            WorkerJob.ingest_fixture_player_stats(
                IngestFixturePlayerStatsJobPayload(fixture_id=1208040)
            )
        )

        self.assertEqual(result.job_type, JobType.INGEST_FIXTURE_PLAYER_STATS)
        self.assertEqual(result.successful_items, 1)
        self.assertEqual(client.stats_calls, [1208040])


def _fixture() -> ApiFootballFixture:
    return ApiFootballFixture(
        provider="https://v3.football.api-sports.io",
        provider_fixture_id="1208040",
        league_provider_id="39",
        season=2025,
        kickoff_at=datetime(2025, 8, 16, 11, 30, tzinfo=UTC),
        home_team_provider_id="42",
        home_team_name="Arsenal",
        away_team_provider_id="50",
        away_team_name="Manchester City",
        status_short="NS",
        status_long="Not Started",
        elapsed=None,
        raw_payload={},
    )


def _player_stat() -> ApiFootballPlayerStat:
    return ApiFootballPlayerStat(
        provider="https://v3.football.api-sports.io",
        provider_fixture_id="1208040",
        provider_player_id="1460",
        team_provider_id="42",
        team_name="Arsenal",
        display_name="Bukayo Saka",
        rating=Decimal("7.8"),
        stats={"games": {"minutes": 90, "rating": "7.8"}},
        raw_payload={},
    )


def _json_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


if __name__ == "__main__":
    unittest.main()
