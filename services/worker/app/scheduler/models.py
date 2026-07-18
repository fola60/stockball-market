from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.jobs.models import (
    IngestBet365OddsJobPayload,
    IngestTwitterInjuriesJobPayload,
    SyntheticTraderTickJobPayload,
    TopupJobPayload,
    WorkerJob,
)
from app.jobs.models import JobType
from app.topups.models import TopupCadence, TopupWindow


class SchedulePlan(Protocol):
    name: str
    enabled: bool

    def window_key_for(self, effective_at: datetime) -> str: ...

    def build_job(self, effective_at: datetime) -> WorkerJob: ...


@dataclass(frozen=True)
class RecurringTopupPlan:
    name: str
    cadence: TopupCadence
    enabled: bool = True

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
class SyntheticTraderTickPlan:
    name: str = "synthetic-trader-ticks"
    interval_minutes: int = 1
    enabled: bool = True

    def window_key_for(self, effective_at: datetime) -> str:
        return _normalize_tick_time(effective_at).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.synthetic_trader_tick(
            SyntheticTraderTickJobPayload(
                effective_at=_normalize_tick_time(effective_at),
            )
        )


@dataclass(frozen=True)
class Bet365OddsIngestionPlan:
    name: str = "bet365-odds"
    interval_minutes: int = 15
    enabled: bool = False

    def window_key_for(self, effective_at: datetime) -> str:
        normalized = _normalize_tick_time(effective_at)
        minute = normalized.minute - (normalized.minute % self.interval_minutes)
        return normalized.replace(minute=minute).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.ingest_bet365_odds(IngestBet365OddsJobPayload())


@dataclass(frozen=True)
class TwitterInjuryIngestionPlan:
    name: str = "twitter-injury-intelligence"
    interval_minutes: int = 5
    query_key: str | None = None
    enabled: bool = False

    def window_key_for(self, effective_at: datetime) -> str:
        normalized = _normalize_tick_time(effective_at)
        minute = normalized.minute - (normalized.minute % self.interval_minutes)
        return normalized.replace(minute=minute).isoformat()

    def build_job(self, effective_at: datetime) -> WorkerJob:
        return WorkerJob.ingest_twitter_injuries(
            IngestTwitterInjuriesJobPayload(query_key=self.query_key)
        )


@dataclass(frozen=True)
class ScheduledJobDecision:
    schedule_name: str
    job_type: JobType
    window_key: str
    job: WorkerJob


def default_scheduler_plans(
    bet365_enabled: bool = False,
    twitter_injury_enabled: bool = False,
    twitter_injury_interval_minutes: int = 5,
    twitter_query_key: str | None = None,
) -> tuple[SchedulePlan, ...]:
    return (
        RecurringTopupPlan(name="weekly-topups", cadence=TopupCadence.WEEKLY),
        RecurringTopupPlan(name="monthly-topups", cadence=TopupCadence.MONTHLY),
        SyntheticTraderTickPlan(),
        Bet365OddsIngestionPlan(enabled=bet365_enabled),
        TwitterInjuryIngestionPlan(
            enabled=twitter_injury_enabled,
            interval_minutes=twitter_injury_interval_minutes,
            query_key=twitter_query_key,
        ),
    )


def _normalize_tick_time(value: datetime) -> datetime:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    normalized = normalized.astimezone(UTC)
    return normalized.replace(second=0, microsecond=0)
