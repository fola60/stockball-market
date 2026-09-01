from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping


BET365_PROVIDER = "BET365"


@dataclass(frozen=True)
class Bet365FixtureListing:
    home_team: str
    away_team: str
    date_label: str | None
    kickoff_time_label: str | None
    kickoff_at: datetime | None
    fractional_odds: tuple[str, str, str]


@dataclass(frozen=True)
class Bet365DiscoveredFixture:
    provider_event_id: str
    home_team: str
    away_team: str
    date_label: str | None
    kickoff_time_label: str | None
    kickoff_at: datetime | None
    source_url: str


@dataclass(frozen=True)
class Bet365CompetitionDiscovery:
    competition_name: str
    competition_url: str
    fixtures: tuple[Bet365DiscoveredFixture, ...]


@dataclass(frozen=True)
class BettingMarketObservation:
    provider: str
    provider_event_id: str
    fixture_provider_id: str | None
    market_key: str
    selection_key: str
    decimal_odds: Decimal
    implied_probability: Decimal
    observed_at: datetime
    source_url: str | None
    raw_payload: Mapping[str, Any]


@dataclass(frozen=True)
class BettingMarketIngestionResult:
    fetched_observations: int
    upserted_observations: int
