from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class ApiFootballPlayerStat:
    provider: str
    provider_fixture_id: str
    provider_player_id: str
    team_provider_id: str | None
    team_name: str | None
    display_name: str
    rating: Decimal | None
    stats: Mapping[str, Any]
    raw_payload: Mapping[str, Any]


@dataclass(frozen=True)
class FixturePlayerStatsIngestionResult:
    fetched_observations: int
    upserted_observations: int
    matched_players: int
