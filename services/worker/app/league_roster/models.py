from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

# One freeze per departed player, so a player who returns can be released on their own.
ROSTER_SOURCE_PREFIX = "not-in-league:"
# The engine's freeze reasons are MATCH_DAY, ADMIN_HALT and DATA_ISSUE; leaving the league is
# a standing halt, told apart from manual halts by its source key.
ROSTER_FREEZE_REASON = "ADMIN_HALT"
# A season's player list smaller than this is treated as incomplete (an empty pre-season page,
# a partial fetch) and never used to halt anyone.
MIN_ROSTER_PLAYERS = 300
MIN_ROSTER_CLUBS = 18


def roster_source_key(player_id: UUID) -> str:
    return f"{ROSTER_SOURCE_PREFIX}{player_id}"


@dataclass(frozen=True)
class RosterMembership:
    instrument_id: UUID
    player_id: UUID
    in_league: bool


@dataclass(frozen=True)
class RosterSyncResult:
    season: int
    fetched_players: int = 0
    clubs_seen: int = 0
    instruments_created: int = 0
    halted: int = 0
    released: int = 0
    skipped_reason: str | None = None
    failures: tuple[str, ...] = field(default_factory=tuple)
