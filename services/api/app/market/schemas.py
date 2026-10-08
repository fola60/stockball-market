from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.market.models import (
    FixtureStatus,
    MarketTradeRecord,
    MatchdayRecord,
    NewsRecord,
    SparklineRange,
)
from app.traders.models import TraderKind


class SparklinesResponse(BaseModel):
    range: SparklineRange
    # Prices oldest first, keyed by instrument ID.
    series: dict[str, list[str]]


class FixtureTeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    team_id: str
    name: str
    short_name: str
    club: str | None
    badge_version: str | None


class FixtureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    match_id: str
    kickoff_at: datetime
    lock_at: datetime
    status: FixtureStatus
    score: str | None
    home: FixtureTeamResponse
    away: FixtureTeamResponse


class RoundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    season: int
    round: int
    fixtures: list[FixtureResponse]


class RatedPlayerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: UUID
    player_name: str
    team_name: str
    rating: str
    goals: int
    home_team: str
    away_team: str
    score: str | None


class MatchdayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lineup_lock_minutes: int
    next_round: RoundResponse | None
    previous_round: int | None
    top_rated: list[RatedPlayerResponse]
    league_clubs: list[str]

    @classmethod
    def from_record(cls, record: MatchdayRecord) -> "MatchdayResponse":
        return cls.model_validate(record)


class MarketTradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trade_id: UUID
    executed_at: datetime
    account_id: UUID
    trader_name: str
    trader_kind: TraderKind
    strategy: str | None
    side: str
    shares: str
    execution_price: str
    gross_amount: str
    instrument_id: UUID
    player_name: str

    @classmethod
    def from_record(cls, record: MarketTradeRecord) -> "MarketTradeResponse":
        return cls.model_validate(record)


class NewsItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    title: str
    url: str
    source: str
    published_at: datetime
    topic: str | None
    player_name: str
    instrument_id: UUID

    @classmethod
    def from_record(cls, record: NewsRecord) -> "NewsItemResponse":
        return cls.model_validate(record)
