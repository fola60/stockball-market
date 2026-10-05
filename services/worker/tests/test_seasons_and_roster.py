from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from uuid import UUID

from app.clients import ApplyFreezeCommand, TradingEngineUnavailableError
from app.clients.trading_engine import ApplyFreezeRecord
from app.ingestion.players.models import PlayerSeedResult
from app.jobs.models import IngestPlayersJobPayload, IngestPlayerStatsJobPayload, JobType
from app.league_roster import LeagueRosterService, RosterMembership
from app.league_roster.models import roster_source_key
from app.scheduler.models import (
    DailyLeagueRosterPlan,
    DailyPlayerStatsIngestionPlan,
    default_scheduler_plans,
)
from app.seasons import current_season, resolve_season, season_for


class SeasonTests(unittest.TestCase):
    def test_season_rolls_over_in_july(self) -> None:
        self.assertEqual(season_for(date(2026, 5, 24)), 2025)
        self.assertEqual(season_for(date(2026, 6, 30)), 2025)
        self.assertEqual(season_for(date(2026, 7, 1)), 2026)
        self.assertEqual(season_for(date(2026, 10, 3)), 2026)
        self.assertEqual(season_for(date(2027, 1, 15)), 2026)

    def test_zero_follows_the_season_in_progress_and_a_year_pins_one(self) -> None:
        autumn = datetime(2026, 10, 3, tzinfo=UTC)
        self.assertEqual(resolve_season(0, autumn), 2026)
        self.assertEqual(resolve_season(None, autumn), 2026)
        self.assertEqual(resolve_season(2024, autumn), 2024)

    def test_job_payloads_default_to_the_season_in_progress(self) -> None:
        self.assertEqual(IngestPlayersJobPayload.from_payload({}).season, current_season())
        self.assertEqual(IngestPlayerStatsJobPayload.from_payload({"season": 0}).season, current_season())
        self.assertEqual(IngestPlayerStatsJobPayload.from_payload({"season": 2024}).season, 2024)

    def test_scheduled_runs_carry_the_resolved_season(self) -> None:
        autumn = datetime(2026, 10, 3, 4, tzinfo=UTC)
        stats = DailyPlayerStatsIngestionPlan().build_job(autumn)
        roster = DailyLeagueRosterPlan().build_job(autumn)
        self.assertEqual(stats.payload["season"], 2026)
        self.assertEqual(roster.job_type, JobType.SYNC_LEAGUE_ROSTER)
        self.assertEqual(roster.payload["season"], 2026)
        pinned = DailyPlayerStatsIngestionPlan(season=2025).build_job(autumn)
        self.assertEqual(pinned.payload["season"], 2025)

    def test_roster_runs_an_hour_before_the_stats_import(self) -> None:
        plans = {plan.name: plan for plan in default_scheduler_plans(player_stats_run_hour_utc=3)}
        roster = plans["daily-league-roster"]
        stats = plans["daily-player-stats"]
        assert isinstance(roster, DailyLeagueRosterPlan)
        assert isinstance(stats, DailyPlayerStatsIngestionPlan)
        self.assertEqual(roster.run_hour_utc, 2)
        self.assertEqual(stats.run_hour_utc, 3)


class FakeRosterRepository:
    def __init__(self, memberships, open_freezes=None) -> None:
        self._memberships = memberships
        self._open = open_freezes or {}

    def memberships(self, season):
        return self._memberships

    def open_roster_freezes(self):
        return self._open


class FakeEngine:
    def __init__(self, fail_on: str | None = None) -> None:
        self.applied: list[ApplyFreezeCommand] = []
        self.released: list[str] = []
        self.fail_on = fail_on

    def apply_freeze(self, command: ApplyFreezeCommand) -> ApplyFreezeRecord:
        if command.source_key == self.fail_on:
            raise TradingEngineUnavailableError("engine down")
        self.applied.append(command)
        return ApplyFreezeRecord(source_key=command.source_key, opened_count=1, already_open_count=0)

    def release_freeze(self, source_key: str):
        self.released.append(source_key)


class FakePlayers:
    def __init__(self, fetched: int, clubs: int) -> None:
        self.result = PlayerSeedResult(fetched_players=fetched, upserted_players=fetched, clubs_seen=clubs)

    def seed_players(self, league, season):
        return self.result


class FakeInstruments:
    def __init__(self) -> None:
        self.calls = 0

    def seed(self):
        self.calls += 1
        return 3, 500


STAYED = RosterMembership(UUID(int=1), UUID(int=101), in_league=True)
LEFT = RosterMembership(UUID(int=2), UUID(int=102), in_league=False)
RETURNED = RosterMembership(UUID(int=3), UUID(int=103), in_league=True)


class LeagueRosterServiceTests(unittest.TestCase):
    def test_halts_departed_players_and_releases_returning_ones(self) -> None:
        engine = FakeEngine()
        repository = FakeRosterRepository(
            [STAYED, LEFT, RETURNED],
            open_freezes={roster_source_key(RETURNED.player_id): {RETURNED.instrument_id}},
        )
        instruments = FakeInstruments()
        service = LeagueRosterService(repository, engine, FakePlayers(600, 20), instruments)

        result = service.sync(9, 2026)

        self.assertEqual([command.source_key for command in engine.applied], [roster_source_key(LEFT.player_id)])
        self.assertEqual(engine.applied[0].instrument_ids, (LEFT.instrument_id,))
        self.assertEqual(engine.applied[0].reason, "ADMIN_HALT")
        self.assertEqual(engine.released, [roster_source_key(RETURNED.player_id)])
        self.assertEqual((result.halted, result.released, result.instruments_created), (1, 1, 3))
        self.assertIsNone(result.skipped_reason)

    def test_already_halted_players_are_not_halted_again(self) -> None:
        engine = FakeEngine()
        repository = FakeRosterRepository(
            [LEFT], open_freezes={roster_source_key(LEFT.player_id): {LEFT.instrument_id}}
        )

        result = LeagueRosterService(repository, engine).reconcile(2026)

        self.assertEqual(engine.applied, [])
        self.assertEqual(engine.released, [])
        self.assertEqual(result.halted, 0)

    def test_an_incomplete_season_list_never_halts_anyone(self) -> None:
        engine = FakeEngine()
        instruments = FakeInstruments()
        service = LeagueRosterService(
            FakeRosterRepository([LEFT]), engine, FakePlayers(40, 3), instruments
        )

        result = service.sync(9, 2026)

        self.assertIsNotNone(result.skipped_reason)
        self.assertEqual(engine.applied, [])
        self.assertEqual(instruments.calls, 0)

    def test_engine_failures_are_reported_without_stopping_the_run(self) -> None:
        other_left = RosterMembership(UUID(int=4), UUID(int=104), in_league=False)
        engine = FakeEngine(fail_on=roster_source_key(LEFT.player_id))

        result = LeagueRosterService(FakeRosterRepository([LEFT, other_left]), engine).reconcile(2026)

        self.assertEqual(result.halted, 1)
        self.assertEqual(len(result.failures), 1)


if __name__ == "__main__":
    unittest.main()
