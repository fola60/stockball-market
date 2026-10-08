from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.common.images import ImageRecord
from app.main import create_app
from app.market.models import (
    FixtureRowRecord,
    FixtureTeamRecord,
    MarketTradeRecord,
    NewsCandidateRecord,
    RatedPlayerRecord,
)
from app.market.service import MAX_SPARKLINE_INSTRUMENTS, MarketService
from app.traders.models import TraderKind

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _team(name: str, club: str | None = None) -> FixtureTeamRecord:
    return FixtureTeamRecord(
        team_id=str(abs(hash(name)) % 100000),
        name=name,
        short_name=name,
        club=club or name,
        badge_version="ab12cd34ef56ab78",
    )


def _fixture(
    match_id: str,
    kickoff_at: datetime,
    *,
    finished: bool = False,
    started: bool = False,
    cancelled: bool = False,
    score: str | None = None,
) -> FixtureRowRecord:
    return FixtureRowRecord(
        match_id=match_id,
        kickoff_at=kickoff_at,
        finished=finished,
        started=started,
        cancelled=cancelled,
        score=score,
        home=_team(f"Home {match_id}"),
        away=_team(f"Away {match_id}"),
    )


def _candidate(
    title: str,
    text: str,
    player_name: str,
    club: str,
    *,
    document_id: UUID | None = None,
    instrument_id: UUID | None = None,
    minutes_ago: int = 0,
) -> NewsCandidateRecord:
    return NewsCandidateRecord(
        document_id=document_id or uuid4(),
        title=title,
        text=text,
        url="https://example.com/story",
        source="Example Sport",
        published_at=NOW - timedelta(minutes=minutes_ago),
        topic="TRANSFER",
        resolution_confidence=0.9,
        player_name=player_name,
        club=club,
        instrument_id=instrument_id or uuid4(),
    )


class FakeMarketRepository:
    def __init__(self) -> None:
        self.upcoming: tuple[int, int] | None = (2026, 6)
        self.fixtures: list[FixtureRowRecord] = []
        self.trades: list[MarketTradeRecord] = []
        self.candidates: list[NewsCandidateRecord] = []
        self.sparkline_calls: list[tuple[list[UUID], timedelta, timedelta]] = []
        self.finished_round_before: int | None = None
        self.club_name_calls = 0

    def sparklines(
        self, instrument_ids: list[UUID], window: timedelta, step: timedelta
    ) -> dict[UUID, list[str]]:
        self.sparkline_calls.append((instrument_ids, window, step))
        return {instrument_id: ["1.0000", "1.2500"] for instrument_id in instrument_ids}

    def upcoming_round(self) -> tuple[int, int] | None:
        return self.upcoming

    def latest_season(self) -> int | None:
        return 2026

    def round_fixtures(self, season: int, round_number: int) -> list[FixtureRowRecord]:
        return self.fixtures

    def latest_finished_round(self, season: int, before: int | None) -> int | None:
        self.finished_round_before = before
        return 5

    def top_rated(self, season: int, round_number: int, limit: int) -> list[RatedPlayerRecord]:
        return [
            RatedPlayerRecord(
                instrument_id=uuid4(),
                player_name="Brian Brobbey",
                team_name="Sunderland",
                rating="9.66",
                goals=3,
                home_team="Man City",
                away_team="Sunderland",
                score="5 - 3",
            )
        ]

    def league_clubs(self, season: int) -> list[str]:
        return ["Arsenal", "Leeds United"]

    def recent_trades(self, window: timedelta, limit: int) -> list[MarketTradeRecord]:
        return self.trades[:limit]

    def news_candidates(self, since: datetime, limit: int) -> list[NewsCandidateRecord]:
        return self.candidates[:limit]

    def club_names(self) -> dict[str, list[str]]:
        self.club_name_calls += 1
        return {
            "Nottingham": ["Nottingham Forest", "Nott'm Forest"],
            "Crystal Palace": ["Crystal Palace"],
            "Arsenal": ["Arsenal"],
        }

    def team_badge(self, team_id: str) -> ImageRecord | None:
        if team_id != "9825":
            return None
        return ImageRecord(data=b"\x89PNG badge", content_type="image/png", content_sha256="cd" * 32)


class MarketHomeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeMarketRepository()
        app = create_app(
            instruments_service=Mock(),
            market_service=MarketService(self.repository, lineup_lock_minutes=60, clock=lambda: NOW),
        )
        self.client = TestClient(app)

    def test_sparklines_dedupe_ids_and_use_the_range_window(self) -> None:
        first, second = uuid4(), uuid4()
        response = self.client.get(
            "/v1/market/sparklines", params={"ids": f"{first},{first},{second}", "range": "1D"}
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["range"], "1D")
        self.assertEqual(set(body["series"]), {str(first), str(second)})
        ids, window, step = self.repository.sparkline_calls[0]
        self.assertEqual(ids, [first, second])
        self.assertEqual((window, step), (timedelta(hours=24), timedelta(hours=2)))

    def test_sparklines_reject_bad_and_excessive_ids(self) -> None:
        bad = self.client.get("/v1/market/sparklines", params={"ids": "not-a-uuid"})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["code"], "invalid_instrument_id")

        many = ",".join(str(uuid4()) for _ in range(MAX_SPARKLINE_INSTRUMENTS + 1))
        too_many = self.client.get("/v1/market/sparklines", params={"ids": many})
        self.assertEqual(too_many.status_code, 422)
        self.assertEqual(too_many.json()["code"], "too_many_instruments")

    def test_matchday_reports_each_fixtures_trading_state(self) -> None:
        self.repository.fixtures = [
            _fixture("upcoming", NOW + timedelta(hours=3)),
            _fixture("locked", NOW + timedelta(minutes=30)),
            _fixture("live", NOW - timedelta(minutes=40), started=True, score="1 - 0"),
            _fixture("done", NOW - timedelta(hours=3), finished=True, score="2 - 2"),
            _fixture("off", NOW + timedelta(hours=1), cancelled=True),
        ]

        body = self.client.get("/v1/market/matchday").json()

        fixtures = {fixture["match_id"]: fixture for fixture in body["next_round"]["fixtures"]}
        self.assertEqual(fixtures["upcoming"]["status"], "UPCOMING")
        self.assertIsNone(fixtures["upcoming"]["score"])
        self.assertEqual(fixtures["locked"]["status"], "PAUSED")
        self.assertEqual(fixtures["live"]["status"], "LIVE")
        self.assertEqual(fixtures["live"]["score"], "1 - 0")
        self.assertEqual(fixtures["done"]["status"], "FINISHED")
        self.assertEqual(fixtures["off"]["status"], "POSTPONED")
        self.assertEqual(
            datetime.fromisoformat(fixtures["upcoming"]["lock_at"]),
            NOW + timedelta(hours=2),
        )
        self.assertEqual(body["next_round"]["round"], 6)
        self.assertEqual(body["previous_round"], 5)
        self.assertEqual(self.repository.finished_round_before, 6)
        self.assertEqual(body["top_rated"][0]["goals"], 3)
        self.assertEqual(body["league_clubs"], ["Arsenal", "Leeds United"])
        self.assertEqual(body["lineup_lock_minutes"], 60)

    def test_matchday_after_the_season_reports_the_last_round(self) -> None:
        self.repository.upcoming = None

        body = self.client.get("/v1/market/matchday").json()

        self.assertIsNone(body["next_round"])
        self.assertEqual(body["previous_round"], 5)
        self.assertIsNone(self.repository.finished_round_before)

    def test_recent_trades_are_returned_newest_first(self) -> None:
        def trade(minutes_ago: int, gross: str) -> MarketTradeRecord:
            return MarketTradeRecord(
                trade_id=uuid4(),
                executed_at=NOW - timedelta(minutes=minutes_ago),
                account_id=uuid4(),
                trader_name="Han Hana",
                trader_kind=TraderKind.BOT,
                strategy="Stats Value Conservative",
                side="BUY",
                shares="174.300000",
                execution_price="14.3300",
                gross_amount=gross,
                instrument_id=uuid4(),
                player_name="James Justin",
            )

        self.repository.trades = [trade(50, "3000.0000"), trade(5, "2497.0000"), trade(20, "2400.0000")]

        body = self.client.get("/v1/market/trades", params={"limit": 3}).json()

        self.assertEqual([item["gross_amount"] for item in body], ["2497.0000", "2400.0000", "3000.0000"])
        self.assertEqual(body[0]["trader_kind"], "BOT")
        self.assertEqual(body[0]["strategy"], "Stats Value Conservative")

    def test_news_needs_the_player_in_the_headline_and_the_club_in_the_story(self) -> None:
        gibbs_white = uuid4()
        self.repository.candidates = [
            _candidate(
                "What a Chelsea move for Gibbs-White would mean",
                "Nottingham Forest would demand a record fee.",
                "Morgan Gibbs-White",
                "Nottingham",
                instrument_id=gibbs_white,
            ),
            _candidate(
                "FIA refutes lack of testing claims",
                "Hughes said the software fix was confirmed.",
                "Will Hughes",
                "Crystal Palace",
            ),
            _candidate(
                "Gibbs-White signs boot deal",
                "A second story about the same player.",
                "Morgan Gibbs-White",
                "Nottingham",
                instrument_id=gibbs_white,
                minutes_ago=5,
            ),
            _candidate(
                "Saka fit for the weekend",
                "The winger trained fully on Thursday.",
                "Bukayo Saka",
                "Arsenal",
                minutes_ago=10,
            ),
            _candidate(
                "Dowman wins three world records",
                "The Arsenal teenager was honoured on Thursday.",
                "Max Dowman",
                "Arsenal",
                minutes_ago=15,
            ),
        ]

        body = self.client.get("/v1/market/news", params={"limit": 3}).json()

        self.assertEqual(
            [item["player_name"] for item in body], ["Morgan Gibbs-White", "Max Dowman"]
        )
        self.assertEqual(body[0]["title"], "What a Chelsea move for Gibbs-White would mean")

        self.client.get("/v1/market/news")
        self.assertEqual(self.repository.club_name_calls, 1)

    def test_team_badge_is_served_by_team_id(self) -> None:
        response = self.client.get("/v1/market/teams/9825/badge")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")

        cached = self.client.get(
            "/v1/market/teams/9825/badge", headers={"If-None-Match": response.headers["etag"]}
        )
        self.assertEqual(cached.status_code, 304)

        missing = self.client.get("/v1/market/teams/1/badge")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["code"], "team_badge_not_found")

        invalid = self.client.get("/v1/market/teams/abc/badge")
        self.assertEqual(invalid.status_code, 422)
