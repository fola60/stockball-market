from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

MATCH_DAY_REASON = "MATCH_DAY"
FIXTURE_SOURCE_PREFIX = "fixture:"
# Fixtures in these states will not be played in their slot, so their players stay tradable.
CALLED_OFF_STATUSES = frozenset({"PST", "CANC", "ABD", "AWD", "WO"})
# A match in one of these states is over.
FINISHED_STATUSES = frozenset({"FT", "AET", "PEN"})


@dataclass(frozen=True)
class MatchFreezeWindow:
    """Trading closes at lineup lock and reopens once the match has been settled.

    Settlement needs both the settlement time to have passed and the match to be reported
    finished, so a delayed, suspended or long match keeps its players frozen until full time.
    `max_hold` is the backstop: if the fixture's status never reports full time, for example
    because fixture ingestion stopped, the freeze still ends that long after kick-off.
    """

    lineup_lock: timedelta = timedelta(minutes=60)
    settlement: timedelta = timedelta(minutes=150)
    max_hold: timedelta = timedelta(minutes=360)

    def __post_init__(self) -> None:
        if self.lineup_lock < timedelta(0) or self.settlement <= timedelta(0):
            raise ValueError("lineup lock must be >= 0 and settlement must be positive")
        if self.max_hold < self.settlement:
            raise ValueError("max hold must be at least the settlement time")


@dataclass(frozen=True)
class FixtureRecord:
    fixture_id: UUID
    kickoff_at: datetime
    home_team_provider_id: str
    away_team_provider_id: str
    home_team_name: str
    away_team_name: str
    status_short: str | None

    @property
    def source_key(self) -> str:
        return f"{FIXTURE_SOURCE_PREFIX}{self.fixture_id}"

    def is_frozen_at(self, now: datetime, window: MatchFreezeWindow) -> bool:
        status = (self.status_short or "").upper()
        if status in CALLED_OFF_STATUSES:
            return False
        if now < self.kickoff_at - window.lineup_lock:
            return False
        if now < self.kickoff_at + window.settlement:
            return True
        return status not in FINISHED_STATUSES and now < self.kickoff_at + window.max_hold


@dataclass(frozen=True)
class MatchFreezeReconciliation:
    fixtures_frozen: int = 0
    fixtures_released: int = 0
    instruments_frozen: int = 0
    instruments_reactivated: int = 0
    failures: tuple[str, ...] = field(default_factory=tuple)
