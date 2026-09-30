from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx

from app.clients import (
    ApplyFreezeCommand,
    ApplyFreezeRecord,
    HttpTradingEngineClient,
    ReleaseFreezeRecord,
    TradingEngineUnavailableError,
)
from app.jobs import (
    CheckMarketFreezesJobHandler,
    CheckMarketFreezesJobPayload,
    JobType,
    RetryableJobError,
    WorkerJob,
)
from app.match_freezes import FixtureRecord, MatchFreezeService, MatchFreezeWindow
from app.queue import TRADING_QUEUE_JOB_TYPES

KICKOFF = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)
WINDOW = MatchFreezeWindow(lineup_lock=timedelta(minutes=60), settlement=timedelta(minutes=150))


class FakeRepository:
    def __init__(self, fixtures, squads, open_freezes=None) -> None:
        self.fixtures = fixtures
        self.squads = squads
        self.open_freezes = open_freezes or {}

    def fixtures_near(self, now, window):
        return self.fixtures

    def instruments_for_teams(self, team_provider_ids):
        return {team: self.squads[team] for team in team_provider_ids if team in self.squads}

    def open_fixture_freezes(self):
        return {key: set(ids) for key, ids in self.open_freezes.items()}


class FakeEngine:
    def __init__(self, repository: FakeRepository | None = None, fail: bool = False) -> None:
        self.repository = repository
        self.fail = fail
        self.applied: list[ApplyFreezeCommand] = []
        self.released: list[str] = []

    def apply_freeze(self, command: ApplyFreezeCommand) -> ApplyFreezeRecord:
        if self.fail:
            raise TradingEngineUnavailableError("engine down")
        self.applied.append(command)
        if self.repository is not None:
            self.repository.open_freezes.setdefault(command.source_key, set()).update(
                command.instrument_ids
            )
        return ApplyFreezeRecord(command.source_key, len(command.instrument_ids), 0)

    def release_freeze(self, source_key: str) -> ReleaseFreezeRecord:
        self.released.append(source_key)
        instrument_ids = ()
        if self.repository is not None:
            instrument_ids = tuple(self.repository.open_freezes.pop(source_key, set()))
        return ReleaseFreezeRecord(source_key, len(instrument_ids), instrument_ids)


def _fixture(status: str | None = "NS", kickoff: datetime = KICKOFF) -> FixtureRecord:
    return FixtureRecord(
        fixture_id=UUID(int=1),
        kickoff_at=kickoff,
        home_team_provider_id="ars",
        away_team_provider_id="che",
        home_team_name="Arsenal",
        away_team_name="Chelsea",
        status_short=status,
    )


SQUADS = {"ars": {UUID(int=10), UUID(int=11)}, "che": {UUID(int=20)}, "mci": {UUID(int=30)}}


class MatchFreezeWindowTests(unittest.TestCase):
    def test_window_runs_from_lineup_lock_until_settlement(self) -> None:
        fixture = _fixture()
        self.assertFalse(fixture.is_frozen_at(KICKOFF - timedelta(minutes=61), WINDOW))
        self.assertTrue(fixture.is_frozen_at(KICKOFF - timedelta(minutes=60), WINDOW))
        self.assertTrue(fixture.is_frozen_at(KICKOFF + timedelta(minutes=149), WINDOW))
        self.assertFalse(fixture.is_frozen_at(KICKOFF + timedelta(minutes=150), WINDOW))

    def test_called_off_fixtures_are_never_frozen(self) -> None:
        for status in ("PST", "CANC", "abd"):
            self.assertFalse(_fixture(status).is_frozen_at(KICKOFF, WINDOW))


class MatchFreezeServiceTests(unittest.TestCase):
    def test_freezes_both_squads_at_lineup_lock(self) -> None:
        repository = FakeRepository([_fixture()], SQUADS)
        engine = FakeEngine(repository)

        result = MatchFreezeService(repository, engine, WINDOW).reconcile(
            KICKOFF - timedelta(minutes=30)
        )

        self.assertEqual(len(engine.applied), 1)
        command = engine.applied[0]
        self.assertEqual(command.reason, "MATCH_DAY")
        self.assertEqual(command.source_key, f"fixture:{UUID(int=1)}")
        self.assertEqual(set(command.instrument_ids), SQUADS["ars"] | SQUADS["che"])
        self.assertNotIn(UUID(int=30), command.instrument_ids)
        self.assertEqual((result.fixtures_frozen, result.instruments_frozen), (1, 3))

    def test_rerunning_does_not_reapply_open_freezes(self) -> None:
        repository = FakeRepository([_fixture()], SQUADS)
        engine = FakeEngine(repository)
        service = MatchFreezeService(repository, engine, WINDOW)

        service.reconcile(KICKOFF)
        second = service.reconcile(KICKOFF + timedelta(minutes=1))

        self.assertEqual(len(engine.applied), 1)
        self.assertEqual(second.fixtures_frozen, 0)
        self.assertEqual(engine.released, [])

    def test_releases_after_settlement_and_for_called_off_matches(self) -> None:
        source_key = f"fixture:{UUID(int=1)}"
        for fixtures, now in (
            ([_fixture()], KICKOFF + timedelta(minutes=150)),
            ([_fixture("PST")], KICKOFF),
            ([], KICKOFF + timedelta(days=1)),
        ):
            repository = FakeRepository(fixtures, SQUADS, {source_key: {UUID(int=10)}})
            engine = FakeEngine(repository)

            result = MatchFreezeService(repository, engine, WINDOW).reconcile(now)

            self.assertEqual(engine.released, [source_key])
            self.assertEqual(engine.applied, [])
            self.assertEqual(result.instruments_reactivated, 1)

    def test_engine_failures_are_reported_not_raised(self) -> None:
        repository = FakeRepository([_fixture()], SQUADS)

        result = MatchFreezeService(repository, FakeEngine(fail=True), WINDOW).reconcile(KICKOFF)

        self.assertEqual(result.fixtures_frozen, 0)
        self.assertEqual(len(result.failures), 1)


class CheckMarketFreezesJobTests(unittest.TestCase):
    def test_job_runs_on_the_trading_queue(self) -> None:
        self.assertIn(JobType.CHECK_MARKET_FREEZES, TRADING_QUEUE_JOB_TYPES)

    def test_handler_reconciles_using_the_current_time(self) -> None:
        repository = FakeRepository([_fixture()], SQUADS)
        engine = FakeEngine(repository)
        handler = CheckMarketFreezesJobHandler(
            MatchFreezeService(repository, engine, WINDOW), clock=lambda: KICKOFF
        )
        stale_job = WorkerJob.check_market_freezes(
            CheckMarketFreezesJobPayload(effective_at=KICKOFF - timedelta(hours=5))
        )

        result = handler.handle(stale_job)

        self.assertEqual(result.metrics["fixtures_frozen"], 1)
        self.assertEqual(len(engine.applied), 1)

    def test_handler_retries_when_the_engine_is_unavailable(self) -> None:
        repository = FakeRepository([_fixture()], SQUADS)
        handler = CheckMarketFreezesJobHandler(
            MatchFreezeService(repository, FakeEngine(fail=True), WINDOW), clock=lambda: KICKOFF
        )
        job = WorkerJob.check_market_freezes(CheckMarketFreezesJobPayload(effective_at=KICKOFF))

        with self.assertRaises(RetryableJobError) as raised:
            handler.handle(job)
        self.assertEqual(raised.exception.result.retryable_failures, 1)


class FreezeClientTests(unittest.TestCase):
    def test_apply_and_release_post_contract_payloads(self) -> None:
        instrument_id = uuid4()
        requests: list[httpx.Request] = []

        def handler(incoming: httpx.Request) -> httpx.Response:
            requests.append(incoming)
            if incoming.url.path.endswith("/apply"):
                return httpx.Response(
                    200,
                    json={
                        "source_key": "fixture:1",
                        "reason": "MATCH_DAY",
                        "opened_count": 1,
                        "already_open_count": 0,
                        "skipped_delisted_count": 0,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "source_key": "fixture:1",
                    "released_count": 1,
                    "reactivated_instrument_ids": [str(instrument_id)],
                },
            )

        client = HttpTradingEngineClient(
            "http://trading-engine.test", transport=httpx.MockTransport(handler)
        )
        applied = client.apply_freeze(
            ApplyFreezeCommand("MATCH_DAY", "fixture:1", (instrument_id,))
        )
        released = client.release_freeze("fixture:1")

        self.assertEqual(requests[0].url.path, "/internal/v1/freezes/apply")
        self.assertEqual(
            json.loads(requests[0].content),
            {
                "reason": "MATCH_DAY",
                "source_key": "fixture:1",
                "instrument_ids": [str(instrument_id)],
            },
        )
        self.assertEqual(requests[1].url.path, "/internal/v1/freezes/release")
        self.assertEqual(json.loads(requests[1].content), {"source_key": "fixture:1"})
        self.assertEqual(applied.opened_count, 1)
        self.assertEqual(released.reactivated_instrument_ids, (instrument_id,))


if __name__ == "__main__":
    unittest.main()
