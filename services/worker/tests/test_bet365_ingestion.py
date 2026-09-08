from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from datetime import UTC, datetime
from io import StringIO

from app.cli import build_parser
from app.ingestion.betting_markets import (
    Bet365DiscoveredFixture,
    BettingMarketIngestionResult,
    BettingMarketIngestionService,
)
from app.jobs import (
    Bet365IngestionMode,
    IngestBet365OddsJobHandler,
    IngestBet365OddsJobPayload,
    JobType,
    WorkerJob,
)
from app.scheduler.models import Bet365LiveOddsIngestionPlan, Bet365OddsIngestionPlan


class FakeService:
    def __init__(self) -> None:
        self.leagues: list[str | None] = []
        self.live_times: list[datetime] = []

    def ingest_pre_match_markets(self, league: str | None) -> BettingMarketIngestionResult:
        self.leagues.append(league)
        return BettingMarketIngestionResult(fetched_observations=3, upserted_observations=3)

    def ingest_live_markets(self, as_of: datetime) -> BettingMarketIngestionResult:
        self.live_times.append(as_of)
        return BettingMarketIngestionResult(fetched_observations=8, upserted_observations=8)


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

    def test_handler_runs_live_refresh_at_scheduled_time(self) -> None:
        service = FakeService()
        handler = IngestBet365OddsJobHandler(
            betting_market_ingestion_service=service,
            clock=lambda: datetime(2026, 7, 12, 12, 5, 30, tzinfo=UTC),
        )
        effective_at = datetime(2026, 7, 12, 12, 5, tzinfo=UTC)

        result = handler.handle(
            WorkerJob.ingest_bet365_odds(
                IngestBet365OddsJobPayload(
                    mode=Bet365IngestionMode.LIVE,
                    effective_at=effective_at,
                )
            )
        )

        self.assertEqual(result.successful_items, 8)
        self.assertEqual(service.live_times, [effective_at])

    def test_live_schedule_plan_claims_each_minute(self) -> None:
        plan = Bet365LiveOddsIngestionPlan(enabled=True)
        effective_at = datetime(2026, 7, 12, 12, 5, 42, tzinfo=UTC)

        payload = IngestBet365OddsJobPayload.from_payload(
            plan.build_job(effective_at).payload
        )

        self.assertEqual(plan.window_key_for(effective_at), "2026-07-12T12:05:00+00:00")
        self.assertEqual(payload.mode, Bet365IngestionMode.LIVE)
        self.assertEqual(payload.effective_at, datetime(2026, 7, 12, 12, 5, tzinfo=UTC))


class Bet365CommandTests(unittest.TestCase):
    def test_live_mode_is_supported(self) -> None:
        args = build_parser().parse_args(["ingest-bet365-odds", "--mode", "LIVE"])

        self.assertEqual(args.mode, "LIVE")

    def test_source_selector_is_not_supported(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            build_parser().parse_args(["ingest-bet365-odds", "--source", "feed"])

        self.assertEqual(raised.exception.code, 2)


class FakeLiveClient:
    def __init__(self) -> None:
        self.fixtures: tuple[Bet365DiscoveredFixture, ...] | None = None

    def list_pre_match_markets(self, league: str | None = None):
        return []

    def list_live_markets(self, fixtures: tuple[Bet365DiscoveredFixture, ...]):
        self.fixtures = fixtures
        return []


class FakeLiveRepository:
    def __init__(self, fixtures: tuple[Bet365DiscoveredFixture, ...]) -> None:
        self.fixtures = fixtures
        self.lookup: tuple[datetime, int, int] | None = None
        self.upserted = None

    def list_live_event_pages(
        self,
        as_of: datetime,
        *,
        event_window_minutes: int,
        limit: int,
    ) -> tuple[Bet365DiscoveredFixture, ...]:
        self.lookup = (as_of, event_window_minutes, limit)
        return self.fixtures

    def upsert_observations(self, observations):
        self.upserted = observations
        return len(observations)


class BettingMarketIngestionServiceTests(unittest.TestCase):
    def test_live_refresh_does_not_open_browser_without_active_events(self) -> None:
        client = FakeLiveClient()
        repository = FakeLiveRepository(())
        service = BettingMarketIngestionService(
            client,
            repository,
            live_event_window_minutes=150,
            live_event_limit=8,
        )
        as_of = datetime(2026, 7, 12, 12, 5, tzinfo=UTC)

        result = service.ingest_live_markets(as_of)

        self.assertEqual(result.fetched_observations, 0)
        self.assertIsNone(client.fixtures)
        self.assertEqual(repository.lookup, (as_of, 150, 8))
        self.assertEqual(repository.upserted, [])


if __name__ == "__main__":
    unittest.main()
