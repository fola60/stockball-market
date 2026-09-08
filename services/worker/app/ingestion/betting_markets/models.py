from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping

BET365_PROVIDER = "BET365"
MATCH_RESULT_1X2 = "MATCH_RESULT_1X2"


class MarketScope(StrEnum):
    MATCH = "MATCH"
    TEAM = "TEAM"
    PLAYER = "PLAYER"
    PLAYER_PAIR = "PLAYER_PAIR"


class MarketPeriod(StrEnum):
    FULL_MATCH = "FULL_MATCH"
    FIRST_HALF = "FIRST_HALF"
    SECOND_HALF = "SECOND_HALF"


class MarketOutcomeType(StrEnum):
    HOME = "HOME"
    DRAW = "DRAW"
    AWAY = "AWAY"
    ANYTIME = "ANYTIME"
    FIRST = "FIRST"
    LAST = "LAST"
    OVER = "OVER"
    UNDER = "UNDER"
    AT_LEAST = "AT_LEAST"
    YES = "YES"
    NO = "NO"


class PlayerMarketType(StrEnum):
    GOALSCORER = "GOALSCORER"
    ASSIST = "ASSIST"
    SCORE_OR_ASSIST = "SCORE_OR_ASSIST"
    SHOTS = "SHOTS"
    SHOTS_ON_TARGET = "SHOTS_ON_TARGET"
    FOULS_COMMITTED = "FOULS_COMMITTED"
    FOULS_DRAWN = "FOULS_DRAWN"
    CARD = "CARD"
    EITHER_TO_SCORE = "EITHER_TO_SCORE"
    EITHER_TO_ASSIST = "EITHER_TO_ASSIST"
    EITHER_TO_SCORE_OR_ASSIST = "EITHER_TO_SCORE_OR_ASSIST"


class MarketParticipantRole(StrEnum):
    PRIMARY = "PRIMARY"
    EITHER = "EITHER"


@dataclass(frozen=True)
class BettingMarketParticipant:
    provider_player_name: str
    role: MarketParticipantRole = MarketParticipantRole.PRIMARY


@dataclass(frozen=True)
class BettingMarketSelection:
    provider: str
    provider_event_id: str
    fixture_provider_id: str | None
    market_scope: MarketScope
    market_type: str
    period: MarketPeriod
    outcome_type: MarketOutcomeType
    line: Decimal | None
    canonical_selection_key: str
    provider_market_label: str
    provider_selection_label: str
    participants: tuple[BettingMarketParticipant, ...]
    raw_payload: Mapping[str, Any]


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
    selection: BettingMarketSelection
    decimal_odds: Decimal
    implied_probability: Decimal
    observed_at: datetime
    source_url: str | None
    raw_payload: Mapping[str, Any]

    @property
    def provider(self) -> str:
        return self.selection.provider

    @property
    def provider_event_id(self) -> str:
        return self.selection.provider_event_id

    @property
    def fixture_provider_id(self) -> str | None:
        return self.selection.fixture_provider_id

    @property
    def market_key(self) -> str:
        return self.selection.market_type

    @property
    def selection_key(self) -> str:
        return self.selection.outcome_type.value


@dataclass(frozen=True)
class BettingMarketIngestionResult:
    fetched_observations: int
    upserted_observations: int
