from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ExternalPlayer:
    provider: str
    provider_player_id: str
    display_name: str
    club: str
    position: str | None
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class PlayerSeedResult:
    fetched_players: int
    upserted_players: int
    clubs_seen: int
