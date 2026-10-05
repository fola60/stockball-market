from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class ExternalPlayerStat:
    provider: str
    provider_fixture_id: str
    provider_player_id: str
    team_provider_id: str | None
    team_name: str | None
    display_name: str
    rating: Decimal | None
    stats: Mapping[str, Any]
    raw_payload: Mapping[str, Any]
    stat_type: str | None = None
    season: int | None = None
    competition: str | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class PlayerStatsIngestionResult:
    fetched_observations: int
    upserted_observations: int
    matched_players: int
    snapshots_recorded: int = 0
