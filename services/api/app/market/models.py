from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.traders.models import TraderKind


class SparklineRange(StrEnum):
    DAY = "1D"
    WEEK = "1W"


class FixtureStatus(StrEnum):
    UPCOMING = "UPCOMING"
    # Inside the lineup lock: the clubs' players are frozen but the match has not started.
    PAUSED = "PAUSED"
    LIVE = "LIVE"
    FINISHED = "FINISHED"
    POSTPONED = "POSTPONED"


@dataclass(frozen=True)
class FixtureTeamRecord:
    team_id: str
    name: str
    short_name: str
    # The canonical players.club this FotMob team maps to, when known.
    club: str | None
    badge_version: str | None


@dataclass(frozen=True)
class FixtureRowRecord:
    """A stored FotMob fixture before its trading state is worked out."""

    match_id: str
    kickoff_at: datetime
    finished: bool
    started: bool
    cancelled: bool
    score: str | None
    home: FixtureTeamRecord
    away: FixtureTeamRecord


@dataclass(frozen=True)
class FixtureRecord:
    match_id: str
    kickoff_at: datetime
    lock_at: datetime
    status: FixtureStatus
    score: str | None
    home: FixtureTeamRecord
    away: FixtureTeamRecord


@dataclass(frozen=True)
class RoundRecord:
    season: int
    round: int
    fixtures: list[FixtureRecord]


@dataclass(frozen=True)
class RatedPlayerRecord:
    instrument_id: UUID
    player_name: str
    team_name: str
    rating: str
    goals: int
    home_team: str
    away_team: str
    score: str | None


@dataclass(frozen=True)
class MatchdayRecord:
    lineup_lock_minutes: int
    next_round: RoundRecord | None
    previous_round: int | None
    top_rated: list[RatedPlayerRecord]
    # Canonical clubs playing in the current season, for league-only views.
    league_clubs: list[str]


@dataclass(frozen=True)
class MarketTradeRecord:
    trade_id: UUID
    executed_at: datetime
    account_id: UUID
    trader_name: str
    trader_kind: TraderKind
    # The synthetic trader's strategy; None for people.
    strategy: str | None
    side: str
    shares: str
    execution_price: str
    gross_amount: str
    instrument_id: UUID
    player_name: str


@dataclass(frozen=True)
class NewsCandidateRecord:
    """A reviewed feed entry linked to a player by the social classifier."""

    document_id: UUID
    title: str
    text: str
    url: str
    source: str
    published_at: datetime
    topic: str | None
    resolution_confidence: float
    player_name: str
    club: str | None
    instrument_id: UUID


@dataclass(frozen=True)
class NewsRecord:
    document_id: UUID
    title: str
    url: str
    source: str
    published_at: datetime
    topic: str | None
    player_name: str
    instrument_id: UUID
