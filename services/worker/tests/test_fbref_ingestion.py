from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Sequence
from unittest.mock import patch

import httpx

from app.ingestion.fbref import (
    FBREF_PROVIDER,
    FbrefClient,
    parse_fixtures,
    parse_player_stats,
    parse_players,
)
from app.ingestion.fixtures import ExternalFixture, FixtureIngestionService
from app.ingestion.stats import ExternalPlayerStat, PlayerStatsIngestionService
from app.jobs import (
    IngestFixturesJobHandler,
    IngestFixturesJobPayload,
    IngestPlayerStatsJobHandler,
    IngestPlayerStatsJobPayload,
    JobType,
    WorkerJob,
)

FIXTURES_DIR = Path(__file__).with_name("fixtures")


class FakeFixtureRepository:
    def __init__(self) -> None:
        self.fixtures: list[ExternalFixture] = []

    def upsert_fixtures(self, fixtures: list[ExternalFixture]) -> int:
        self.fixtures.extend(fixtures)
        return len(fixtures)


class FakeStatsRepository:
    def __init__(self, matched_players: int = 0) -> None:
        self.observations: list[ExternalPlayerStat] = []
        self.matched_players = matched_players

    def upsert_player_stats(self, observations: list[ExternalPlayerStat]) -> tuple[int, int]:
        self.observations.extend(observations)
        return len(observations), self.matched_players


class FakeFbrefClient:
    def __init__(
        self,
        fixtures: list[ExternalFixture] | None = None,
        stats: list[ExternalPlayerStat] | None = None,
    ) -> None:
        self.fixtures = fixtures or []
        self.stats = stats or []
        self.fixture_calls: list[tuple[int, int, date | None, date | None]] = []
        self.stats_calls: list[tuple[int, int, tuple[str, ...] | None]] = []

    def list_fixtures(
        self,
        league: int,
        season: int,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ExternalFixture]:
        self.fixture_calls.append((league, season, from_date, to_date))
        return self.fixtures

    def list_player_stats(
        self,
        league: int,
        season: int,
        stat_types: Sequence[str] | None = None,
    ) -> list[ExternalPlayerStat]:
        self.stats_calls.append(
            (league, season, None if stat_types is None else tuple(stat_types))
        )
        return self.stats


class FbrefParserTests(unittest.TestCase):
    def test_parse_fixtures_handles_commented_table_and_provider_ids(self) -> None:
        fixtures = parse_fixtures(
            _fixture_html("fbref_schedule.html"),
            source_url="https://fbref.com/en/comps/9/2025-2026/schedule/test",
            season=2025,
        )

        self.assertEqual(len(fixtures), 2)
        self.assertEqual(fixtures[0].provider, FBREF_PROVIDER)
        self.assertEqual(fixtures[0].provider_fixture_id, "9:2025:1:822bd0ba:4ba7cbea")
        self.assertEqual(fixtures[0].provider_match_id, "abcd1234")
        self.assertEqual(fixtures[0].kickoff_at, datetime(2025, 8, 15, 19, 0, tzinfo=UTC))
        self.assertEqual(fixtures[0].home_team_name, "Liverpool")
        self.assertEqual(fixtures[0].status_short, "FT")
        self.assertEqual(fixtures[1].status_short, "NS")
        self.assertIsNone(fixtures[1].provider_match_id)
        self.assertIn("fbref_raw_row", fixtures[0].raw_payload)

    def test_parse_players_from_standard_stats(self) -> None:
        players = parse_players(
            _fixture_html("fbref_standard_stats.html"),
            source_url="https://fbref.com/en/comps/9/2025-2026/stats/test",
            season=2025,
        )

        self.assertEqual(len(players), 2)
        self.assertEqual(players[0].provider, FBREF_PROVIDER)
        self.assertEqual(players[0].provider_player_id, "bc7dc64d")
        self.assertEqual(players[0].display_name, "Bukayo Saka")
        self.assertEqual(players[0].club, "Arsenal")
        self.assertEqual(players[0].metadata["team_provider_id"], "18bb7c10")
        self.assertEqual(players[0].metadata["provider_url"], "https://fbref.com/en/players/bc7dc64d/Bukayo-Saka")
        self.assertIn("fbref_raw_row", players[0].metadata)

    def test_parse_player_stats_normalizes_values_and_keeps_raw_row(self) -> None:
        observations = parse_player_stats(
            _fixture_html("fbref_standard_stats.html"),
            source_url="https://fbref.com/en/comps/9/2025-2026/stats/test",
            season=2025,
            stat_type="standard",
        )

        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[0].provider_player_id, "bc7dc64d")
        self.assertEqual(observations[0].provider_fixture_id, "9:2025:standard:18bb7c10")
        self.assertEqual(observations[0].stat_type, "standard")
        self.assertEqual(observations[0].stats["goals"], 1)
        self.assertEqual(observations[0].stats["minutes"], 180)
        self.assertIn("fbref_raw_row", observations[0].raw_payload)


class FbrefClientTests(unittest.TestCase):
    def test_browser_fallback_response_exposes_page_source_text(self) -> None:
        page_source = (
            "<html><body><table><tr>"
            "<td data-stat='player'>FBref fallback page</td>"
            "</tr></table></body></html>"
        )

        class FakeBrowser:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

            def __enter__(self) -> "FakeBrowser":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def open(self, url: str) -> None:
                self.url = url

            def sleep(self, seconds: float) -> None:
                self.seconds = seconds

            def get_page_source(self) -> str:
                return page_source

            def get_cookies(self) -> list[dict[str, str]]:
                return [{"name": "fbref", "value": "session"}]

        client = FbrefClient(request_interval_seconds=0)

        with patch("app.ingestion.fbref.client.SB", FakeBrowser):
            response = client._request_with_browser("https://fbref.com/en/comps/9/test")

        self.assertEqual(response.content, page_source.encode("utf-8"))
        self.assertEqual(response.text, page_source)

    def test_browser_fallback_waits_for_challenge_and_table_content(self) -> None:
        challenge = "<html><title>Just a moment...</title></html>"
        loaded = "<html><table><td data-stat='player'>Saka</td></table></html>"

        class FakeBrowser:
            instance: "FakeBrowser | None" = None

            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                self.polls = 0
                self.sleeps: list[float] = []
                FakeBrowser.instance = self

            def __enter__(self) -> "FakeBrowser":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def open(self, url: str) -> None:
                self.url = url

            def sleep(self, seconds: float) -> None:
                self.sleeps.append(seconds)
                self.polls += 1

            def get_page_source(self) -> str:
                return challenge if self.polls < 2 else loaded

            def get_cookies(self) -> list[dict[str, str]]:
                return []

        client = FbrefClient(request_interval_seconds=0)

        with patch("app.ingestion.fbref.client.SB", FakeBrowser):
            response = client._request_with_browser("https://fbref.com/en/comps/9/test")

        self.assertEqual(response.text, loaded)
        self.assertEqual(FakeBrowser.instance.sleeps, [1.0, 1.0])

    def test_client_fetches_fbref_fixture_player_and_stat_pages(self) -> None:
        paths_seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths_seen.append(request.url.path)
            if "/schedule/" in request.url.path:
                return _html_response(_fixture_html("fbref_schedule.html"))
            if "/shooting/" in request.url.path:
                return _html_response(_fixture_html("fbref_shooting_stats.html"))
            return _html_response(_fixture_html("fbref_standard_stats.html"))

        client = FbrefClient(
            request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
        )

        fixtures = client.list_fixtures(league=9, season=2025)
        players = client.list_league_players(league=9, season=2025)
        stats = client.list_player_stats(league=9, season=2025, stat_types=("shooting",))

        self.assertEqual(len(fixtures), 2)
        self.assertEqual(len(players), 2)
        self.assertEqual(len(stats), 1)
        self.assertIn("/en/comps/9/2025-2026/schedule/2025-2026-Premier-League-Scores-and-Fixtures", paths_seen)
        self.assertIn("/en/comps/9/2025-2026/stats/2025-2026-Premier-League-Stats", paths_seen)
        self.assertIn("/en/comps/9/2025-2026/shooting/2025-2026-Premier-League-Stats", paths_seen)

    def test_client_retries_transient_rate_limit_response(self) -> None:
        calls = 0
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            if request.url.path == "/":
                return _html_response(_fixture_html("fbref_standard_stats.html"))
            calls += 1
            if calls == 1:
                return httpx.Response(429, headers={"Retry-After": "2"})
            return _html_response(_fixture_html("fbref_standard_stats.html"))

        client = FbrefClient(
            request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
            sleeper=sleeps.append,
        )

        players = client.list_league_players(league=9, season=2025)

        self.assertEqual(len(players), 2)
        self.assertEqual(calls, 2)
        self.assertEqual(sleeps, [2.0])


class FbrefServiceTests(unittest.TestCase):
    def test_fixture_handler_ingests_fbref_fixtures(self) -> None:
        fixture = parse_fixtures(
            _fixture_html("fbref_schedule.html"),
            source_url="https://fbref.com/en/comps/9/2025-2026/schedule/test",
            season=2025,
        )[0]
        client = FakeFbrefClient(fixtures=[fixture])
        service = FixtureIngestionService(client=client, repository=FakeFixtureRepository())
        handler = IngestFixturesJobHandler(
            fixture_ingestion_service=service,
            clock=lambda: datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
        )

        result = handler.handle(
            WorkerJob.ingest_fixtures(
                IngestFixturesJobPayload(
                    league=9,
                    season=2025,
                    from_date=date(2025, 8, 15),
                    to_date=date(2025, 8, 16),
                )
            )
        )

        self.assertEqual(result.job_type, JobType.INGEST_FIXTURES)
        self.assertEqual(result.successful_items, 1)
        self.assertEqual(client.fixture_calls[0][0], 9)

    def test_player_stats_handler_ingests_fbref_stat_tables(self) -> None:
        observation = parse_player_stats(
            _fixture_html("fbref_shooting_stats.html"),
            source_url="https://fbref.com/en/comps/9/2025-2026/shooting/test",
            season=2025,
            stat_type="shooting",
        )[0]
        client = FakeFbrefClient(stats=[observation])
        service = PlayerStatsIngestionService(
            client=client,
            repository=FakeStatsRepository(matched_players=1),
        )
        handler = IngestPlayerStatsJobHandler(
            stats_ingestion_service=service,
            clock=lambda: datetime(2026, 4, 26, 12, 0, tzinfo=UTC),
        )

        result = handler.handle(
            WorkerJob.ingest_player_stats(
                IngestPlayerStatsJobPayload(
                    league=9,
                    season=2025,
                    stat_types=("shooting",),
                )
            )
        )

        self.assertEqual(result.job_type, JobType.INGEST_PLAYER_STATS)
        self.assertEqual(result.successful_items, 1)
        self.assertEqual(client.stats_calls, [(9, 2025, ("shooting",))])


def _fixture_html(filename: str) -> str:
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


def _html_response(body: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body.encode("utf-8"),
        headers={"content-type": "text/html; charset=utf-8"},
    )


if __name__ == "__main__":
    unittest.main()
