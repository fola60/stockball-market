from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.jobs.models import (
    Bet365IngestionMode,
    CheckMarketFreezesJobPayload,
    IngestBet365OddsJobPayload,
    IngestPlayersJobPayload,
    IngestPlayerStatsJobPayload,
    IngestSocialSourceJobPayload,
    IngestTwitterInjuriesJobPayload,
    JobType,
    SyntheticTraderTickJobPayload,
    TopupJobPayload,
    WorkerJob,
)
from app.seasons import CURRENT_SEASON, resolve_season
from app.topups.models import TopupCadence, TopupWindow


class SchedulePlan(Protocol):
    name: str
    enabled: bool
    supersede_pending: bool

    def window_key_for(self, effective_at: datetime) -> str: ...

    def build_job(self, effective_at: datetime) -> WorkerJob: ...


@dataclass(frozen=True)
class RecurringTopupPlan:
    name: str
    cadence: TopupCadence
    enabled: bool = True
    supersede_pending: bool = False

    def window_for(self, effective_at: datetime) -> TopupWindow:
        return TopupWindow.for_datetime(self.cadence, effective_at)

    def window_key_for(self, effective_at: datetime) -> str:
        return self.window_for(effective_at).key

    def build_job(self, effective_at: datetime) -> WorkerJob:
        window = self.window_for(effective_at)
        return WorkerJob.topup(
            TopupJobPayload(
                cadence=self.cadence,
                effective_at=window.start,
            )
        )


@dataclass(frozen=True)
class MarketFreezeCheckPlan:
    """Every minute, open and release match-day freezes around fixtures."""

    name: str = "market-freezes"
    interval_minutes: int = 1
    enabled: bool = True
    supersede_pending: bool = True

    def window_key_for(self, effective_at: datetime) -> str:
        return _normalize_tick_time(effective_at).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.check_market_freezes(
            CheckMarketFreezesJobPayload(effective_at=_normalize_tick_time(effective_at))
        )


@dataclass(frozen=True)
class SyntheticTraderTickPlan:
    name: str = "synthetic-trader-ticks"
    interval_minutes: int = 1
    enabled: bool = True
    supersede_pending: bool = True

    def window_key_for(self, effective_at: datetime) -> str:
        return _normalize_tick_time(effective_at).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.synthetic_trader_tick(
            SyntheticTraderTickJobPayload(
                effective_at=_normalize_tick_time(effective_at),
            )
        )


@dataclass(frozen=True)
class DailyPlayerStatsIngestionPlan:
    name: str = "daily-player-stats"
    league: int = 9
    # 0 means the season in progress, resolved each time a run is scheduled.
    season: int = CURRENT_SEASON
    run_hour_utc: int = 3
    enabled: bool = True
    supersede_pending: bool = True

    def __post_init__(self) -> None:
        if self.league <= 0:
            raise ValueError("player stats league must be positive")
        if self.season < 0:
            raise ValueError("player stats season must be 0 (current) or a season year")
        if not 0 <= self.run_hour_utc <= 23:
            raise ValueError("player stats run_hour_utc must be between 0 and 23")

    def window_key_for(self, effective_at: datetime) -> str:
        return self._window_start(effective_at).date().isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.ingest_player_stats(
            IngestPlayerStatsJobPayload(
                league=self.league, season=resolve_season(self.season, effective_at)
            )
        )

    def _window_start(self, effective_at: datetime) -> datetime:
        normalized = _normalize_timestamp(effective_at)
        start = normalized.replace(
            hour=self.run_hour_utc,
            minute=0,
            second=0,
            microsecond=0,
        )
        return start if normalized >= start else start - timedelta(days=1)


@dataclass(frozen=True)
class DailyLeagueRosterPlan:
    """Daily, before the stats import: refresh the season's players, list newcomers, and halt
    players who have left the league."""

    name: str = "daily-league-roster"
    league: int = 9
    # 0 means the season in progress, resolved each time a run is scheduled.
    season: int = CURRENT_SEASON
    run_hour_utc: int = 2
    enabled: bool = True
    supersede_pending: bool = True

    def __post_init__(self) -> None:
        if self.league <= 0:
            raise ValueError("league roster league must be positive")
        if self.season < 0:
            raise ValueError("league roster season must be 0 (current) or a season year")
        if not 0 <= self.run_hour_utc <= 23:
            raise ValueError("league roster run_hour_utc must be between 0 and 23")

    def window_key_for(self, effective_at: datetime) -> str:
        return self._window_start(effective_at).date().isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.sync_league_roster(
            IngestPlayersJobPayload(
                league=self.league, season=resolve_season(self.season, effective_at)
            )
        )

    def _window_start(self, effective_at: datetime) -> datetime:
        normalized = _normalize_timestamp(effective_at)
        start = normalized.replace(
            hour=self.run_hour_utc,
            minute=0,
            second=0,
            microsecond=0,
        )
        return start if normalized >= start else start - timedelta(days=1)


@dataclass(frozen=True)
class FotMobRatingsIngestionPlan:
    name: str = "fotmob-post-match-ratings"
    enabled: bool = False
    supersede_pending: bool = True

    def window_key_for(self, effective_at: datetime) -> str:
        normalized = _normalize_tick_time(effective_at)
        return normalized.replace(minute=normalized.minute // 15 * 15).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob(JobType.INGEST_FOTMOB_RATINGS,
                         {"league": 47, "season": resolve_season(0, effective_at), "limit": 40})


@dataclass(frozen=True)
class Bet365OddsIngestionPlan:
    name: str = "bet365-odds"
    interval_minutes: int = 15
    enabled: bool = False
    supersede_pending: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.interval_minutes <= 60:
            raise ValueError("Bet365 interval_minutes must be between 1 and 60")

    def window_key_for(self, effective_at: datetime) -> str:
        normalized = _normalize_tick_time(effective_at)
        minute = normalized.minute - (normalized.minute % self.interval_minutes)
        return normalized.replace(minute=minute).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.ingest_bet365_odds(
            IngestBet365OddsJobPayload(mode=Bet365IngestionMode.PRE_MATCH)
        )


@dataclass(frozen=True)
class Bet365LiveOddsIngestionPlan:
    name: str = "bet365-live-odds"
    interval_minutes: int = 1
    enabled: bool = False
    supersede_pending: bool = True

    def __post_init__(self) -> None:
        if self.interval_minutes <= 0:
            raise ValueError("Bet365 live interval_minutes must be positive")

    def window_key_for(self, effective_at: datetime) -> str:
        normalized = _normalize_tick_time(effective_at)
        minute = normalized.minute - (normalized.minute % self.interval_minutes)
        return normalized.replace(minute=minute).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        normalized = _normalize_tick_time(effective_at)
        return WorkerJob.ingest_bet365_odds(
            IngestBet365OddsJobPayload(
                mode=Bet365IngestionMode.LIVE,
                effective_at=normalized,
            )
        )


@dataclass(frozen=True)
class TwitterInjuryIngestionPlan:
    name: str = "twitter-injury-intelligence"
    interval_minutes: int = 5
    query_key: str | None = None
    enabled: bool = False
    supersede_pending: bool = True

    def window_key_for(self, effective_at: datetime) -> str:
        normalized = _normalize_tick_time(effective_at)
        minute = normalized.minute - (normalized.minute % self.interval_minutes)
        return normalized.replace(minute=minute).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.ingest_twitter_injuries(
            IngestTwitterInjuriesJobPayload(query_key=self.query_key)
        )


@dataclass(frozen=True)
class SocialSubscriptionIngestionPlan:
    subscription_id: UUID
    interval_minutes: int
    enabled: bool = True
    supersede_pending: bool = True

    @property
    def name(self) -> str:
        return f"social-source-{self.subscription_id}"

    def __post_init__(self) -> None:
        if self.interval_minutes <= 0:
            raise ValueError("social subscription interval_minutes must be positive")

    def window_key_for(self, effective_at: datetime) -> str:
        normalized = _normalize_tick_time(effective_at)
        minute = normalized.minute - (normalized.minute % self.interval_minutes)
        return normalized.replace(minute=minute).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.ingest_social_source(
            IngestSocialSourceJobPayload(subscription_id=self.subscription_id)
        )


@dataclass(frozen=True)
class ScheduledJobDecision:
    schedule_name: str
    job_type: JobType
    window_key: str
    job: WorkerJob


def default_scheduler_plans(
    player_stats_enabled: bool = True,
    player_stats_run_hour_utc: int = 3,
    player_stats_league: int = 9,
    player_stats_season: int = CURRENT_SEASON,
    bet365_enabled: bool = False,
    bet365_interval_minutes: int = 15,
    bet365_live_enabled: bool = False,
    bet365_live_interval_minutes: int = 1,
    twitter_injury_enabled: bool = False,
    twitter_injury_interval_minutes: int = 5,
    twitter_query_key: str | None = None,
    market_freezes_enabled: bool = True,
    fotmob_enabled: bool = False,
) -> tuple[SchedulePlan, ...]:
    return (
        RecurringTopupPlan(name="weekly-topups", cadence=TopupCadence.WEEKLY),
        RecurringTopupPlan(name="monthly-topups", cadence=TopupCadence.MONTHLY),
        MarketFreezeCheckPlan(enabled=market_freezes_enabled),
        SyntheticTraderTickPlan(),
        # The roster runs an hour before the stats import so new players have records first.
        DailyLeagueRosterPlan(
            enabled=player_stats_enabled,
            run_hour_utc=(player_stats_run_hour_utc - 1) % 24,
            league=player_stats_league,
            season=player_stats_season,
        ),
        DailyPlayerStatsIngestionPlan(
            enabled=player_stats_enabled,
            run_hour_utc=player_stats_run_hour_utc,
            league=player_stats_league,
            season=player_stats_season,
        ),
        FotMobRatingsIngestionPlan(enabled=fotmob_enabled),
        Bet365OddsIngestionPlan(
            enabled=bet365_enabled,
            interval_minutes=bet365_interval_minutes,
        ),
        Bet365LiveOddsIngestionPlan(
            enabled=bet365_live_enabled,
            interval_minutes=bet365_live_interval_minutes,
        ),
        TwitterInjuryIngestionPlan(
            enabled=twitter_injury_enabled,
            interval_minutes=twitter_injury_interval_minutes,
            query_key=twitter_query_key,
        ),
    )


def _normalize_tick_time(value: datetime) -> datetime:
    normalized = _normalize_timestamp(value)
    return normalized.replace(second=0, microsecond=0)


def _normalize_timestamp(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC)
