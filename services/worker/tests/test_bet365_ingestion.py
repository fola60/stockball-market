from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.ingestion.betting_markets import (
    Bet365Client,
    Bet365SourceDisabledError,
    BettingMarketIngestionResult,
    BettingMarketIngestionService,
)
from app.jobs import IngestBet365OddsJobHandler, IngestBet365OddsJobPayload, JobType, WorkerJob
from app.scheduler.models import Bet365OddsIngestionPlan


class FakeRepository:
    def __init__(self) -> None:
        self.observations = []

    def upsert_observations(self, observations: list[object]) -> int:
        self.observations.extend(observations)
        return len(observations)


class FakeService:
    def __init__(self) -> None:
        self.leagues: list[str | None] = []

    def ingest_pre_match_1x2(self, league: str | None) -> BettingMarketIngestionResult:
        self.leagues.append(league)
        return BettingMarketIngestionResult(fetched_observations=3, upserted_observations=3)


class Bet365ClientTests(unittest.TestCase):
    def test_normalizes_only_valid_1x2_selections(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.params["league"], "PL")
            self.assertEqual(request.headers["authorization"], "Bearer token")
            return httpx.Response(
                200,
                json={
                    "observed_at": "2026-07-12T12:00:00Z",
                    "events": [{
                        "id": "event-1",
                        "stockball_fixture_provider_id": "fixture-1",
                        "markets": [
                            {"key": "1X2", "selections": [
                                {"key": "HOME", "odds": "2.10"},
                                {"key": "DRAW", "odds": 3.4},
                                {"key": "AWAY", "odds": 1},
                            ]},
                            {"key": "BTTS", "selections": [{"key": "YES", "odds": 1.9}]},
                        ],
                    }],
                },
            )

        client = Bet365Client(
            "https://licensed.example", "token", request_interval_seconds=0,
            transport=httpx.MockTransport(handler),
        )
        observations = client.list_pre_match_1x2("PL")

        self.assertEqual(len(observations), 2)
        self.assertEqual(observations[0].fixture_provider_id, "fixture-1")
        self.assertEqual(observations[0].decimal_odds, Decimal("2.10"))
        self.assertEqual(observations[0].implied_probability, Decimal("1") / Decimal("2.10"))
        self.assertEqual(observations[0].observed_at, datetime(2026, 7, 12, 12, 0, tzinfo=UTC))

    def test_disabled_source_does_not_make_a_request(self) -> None:
        client = Bet365Client(None, None)
        with self.assertRaises(Bet365SourceDisabledError):
            client.list_pre_match_1x2()

    def test_service_persists_normalized_observations(self) -> None:
        client = Bet365Client(
            "https://licensed.example", None, request_interval_seconds=0,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
                "events": [{"id": "event-1", "markets": [{"key": "1X2", "selections": [{"key": "HOME", "odds": 2}]}]}]
            })),
        )
        repository = FakeRepository()
        result = BettingMarketIngestionService(client, repository).ingest_pre_match_1x2()
        self.assertEqual(result.fetched_observations, 1)
        self.assertEqual(result.upserted_observations, 1)
        self.assertEqual(len(repository.observations), 1)


class Bet365JobTests(unittest.TestCase):
    def test_handler_runs_service_and_reports_upserts(self) -> None:
        service = FakeService()
        handler = IngestBet365OddsJobHandler(
            betting_market_ingestion_service=service,
            clock=lambda: datetime(2026, 7, 12, 12, 5, tzinfo=UTC),
        )
        result = handler.handle(WorkerJob.ingest_bet365_odds(IngestBet365OddsJobPayload("PL")))
        self.assertEqual(result.job_type, JobType.INGEST_BET365_ODDS)
        self.assertEqual(result.successful_items, 3)
        self.assertEqual(service.leagues, ["PL"])

    def test_schedule_plan_claims_one_window_per_quarter_hour(self) -> None:
        plan = Bet365OddsIngestionPlan(enabled=True)
        self.assertEqual(
            plan.window_key_for(datetime(2026, 7, 12, 12, 29, tzinfo=UTC)),
            "2026-07-12T12:15:00+00:00",
        )
        self.assertEqual(plan.build_job(datetime.now(UTC)).job_type, JobType.INGEST_BET365_ODDS)


if __name__ == "__main__":
    unittest.main()
