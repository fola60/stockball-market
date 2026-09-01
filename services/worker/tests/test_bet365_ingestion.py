from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from datetime import UTC, datetime
from io import StringIO

from app.ingestion.betting_markets import BettingMarketIngestionResult
from app.jobs import IngestBet365OddsJobHandler, IngestBet365OddsJobPayload, JobType, WorkerJob
from app.main import _build_parser
from app.scheduler.models import Bet365OddsIngestionPlan


class FakeService:
    def __init__(self) -> None:
        self.leagues: list[str | None] = []

    def ingest_pre_match_1x2(self, league: str | None) -> BettingMarketIngestionResult:
        self.leagues.append(league)
        return BettingMarketIngestionResult(fetched_observations=3, upserted_observations=3)


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


class Bet365CommandTests(unittest.TestCase):
    def test_source_selector_is_not_supported(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            _build_parser().parse_args(["ingest-bet365-odds", "--source", "feed"])

        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
