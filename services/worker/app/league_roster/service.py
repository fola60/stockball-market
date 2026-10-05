from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Protocol

from app.clients import (
    ApplyFreezeCommand,
    FreezeClient,
    TradingEngineClientError,
    TradingEngineUnavailableError,
)
from app.ingestion.players.models import PlayerSeedResult

from .models import (
    MIN_ROSTER_CLUBS,
    MIN_ROSTER_PLAYERS,
    ROSTER_FREEZE_REASON,
    RosterSyncResult,
    roster_source_key,
)
from .repository import LeagueRosterRepository

logger = logging.getLogger(__name__)


class PlayerSeeder(Protocol):
    def seed_players(self, league: int, season: int) -> PlayerSeedResult: ...


class InstrumentSeeder(Protocol):
    def seed(self) -> tuple[int, int]: ...


@dataclass
class LeagueRosterService:
    repository: LeagueRosterRepository
    engine: FreezeClient
    players: PlayerSeeder | None = None
    instruments: InstrumentSeeder | None = None

    def sync(self, league: int, season: int) -> RosterSyncResult:
        """Refresh the season's players, list newcomers, and halt or release players."""
        if self.players is None or self.instruments is None:
            raise RuntimeError("roster sync needs a player seeder and an instrument seeder")
        seeded = self.players.seed_players(league, season)
        result = RosterSyncResult(
            season=season,
            fetched_players=seeded.fetched_players,
            clubs_seen=seeded.clubs_seen,
        )
        if seeded.fetched_players < MIN_ROSTER_PLAYERS or seeded.clubs_seen < MIN_ROSTER_CLUBS:
            reason = (
                f"season {season} list looks incomplete ({seeded.fetched_players} players from "
                f"{seeded.clubs_seen} clubs); no players were halted"
            )
            logger.warning("league roster sync skipped: %s", reason)
            return replace(result, skipped_reason=reason)
        created, _ = self.instruments.seed()
        return replace(self.reconcile(season), fetched_players=seeded.fetched_players,
                       clubs_seen=seeded.clubs_seen, instruments_created=created)

    def reconcile(self, season: int) -> RosterSyncResult:
        """Halt every listed player outside the season's roster and release those back in it.

        Idempotent: the engine ignores freezes that are already open or already released.
        """
        desired = {
            roster_source_key(membership.player_id): membership.instrument_id
            for membership in self.repository.memberships(season)
            if not membership.in_league
        }
        open_freezes = self.repository.open_roster_freezes()
        halted = released = 0
        failures: list[str] = []
        for source_key, instrument_id in sorted(desired.items()):
            if instrument_id in open_freezes.get(source_key, set()):
                continue
            try:
                outcome = self.engine.apply_freeze(
                    ApplyFreezeCommand(
                        reason=ROSTER_FREEZE_REASON,
                        source_key=source_key,
                        instrument_ids=(instrument_id,),
                    )
                )
            except (TradingEngineClientError, TradingEngineUnavailableError) as error:
                failures.append(f"halt {source_key}: {error}")
                continue
            halted += outcome.opened_count
        for source_key in sorted(open_freezes.keys() - desired.keys()):
            try:
                self.engine.release_freeze(source_key)
            except (TradingEngineClientError, TradingEngineUnavailableError) as error:
                failures.append(f"release {source_key}: {error}")
                continue
            released += 1
        return RosterSyncResult(
            season=season, halted=halted, released=released, failures=tuple(failures)
        )
