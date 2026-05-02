from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class ExternalFixture:
    provider: str
    provider_fixture_id: str
    league_provider_id: str
    season: int
    kickoff_at: datetime
    home_team_provider_id: str
    home_team_name: str
    away_team_provider_id: str
    away_team_name: str
    status_short: str | None
    status_long: str | None
    elapsed: int | None
    raw_payload: Mapping[str, Any]
    competition: str | None = None
    source_url: str | None = None
    provider_match_id: str | None = None


@dataclass(frozen=True)
class FixtureIngestionResult:
    fetched_fixtures: int
    upserted_fixtures: int
