from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

MATCH_DAY_REASON = "MATCH_DAY"
FIXTURE_SOURCE_PREFIX = "fixture:"
# Fixtures in these states will not be played in their slot, so their players stay tradable.
CALLED_OFF_STATUSES = frozenset({"PST", "CANC", "ABD", "AWD", "WO"})


@dataclass(frozen=True)
class MatchFreezeWindow:
    """Trading closes at lineup lock and reopens once the match has been settled."""

    lineup_lock: timedelta = timedelta(minutes=60)
    settlement: timedelta = timedelta(minutes=150)

    def __post_init__(self) -> None:
        if self.lineup_lock < timedelta(0) or self.settlement <= timedelta(0):
            raise ValueError("lineup lock must be >= 0 and settlement must be positive")


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
        if (self.status_short or "").upper() in CALLED_OFF_STATUSES:
            return False
        return self.kickoff_at - window.lineup_lock <= now < self.kickoff_at + window.settlement


@dataclass(frozen=True)
class MatchFreezeReconciliation:
    fixtures_frozen: int = 0
    fixtures_released: int = 0
    instruments_frozen: int = 0
    instruments_reactivated: int = 0
    failures: tuple[str, ...] = field(default_factory=tuple)
