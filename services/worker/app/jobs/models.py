from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Mapping

from app.topups.models import TopupCadence


class JobType(StrEnum):
    APPLY_TOPUPS = "APPLY_TOPUPS"
    SYNTHETIC_TRADER_TICK = "SYNTHETIC_TRADER_TICK"
    CHECK_MARKET_FREEZES = "CHECK_MARKET_FREEZES"
    INGEST_PLAYERS = "INGEST_PLAYERS"
    INGEST_FIXTURES = "INGEST_FIXTURES"
    INGEST_PLAYER_STATS = "INGEST_PLAYER_STATS"
    IMPORT_MARKET_VALUES = "IMPORT_MARKET_VALUES"
    INGEST_BET365_ODDS = "INGEST_BET365_ODDS"


@dataclass(frozen=True)
class TopupJobPayload:
    cadence: TopupCadence
    effective_at: datetime

    def to_payload(self) -> dict[str, str]:
        return {
            "cadence": self.cadence.value,
            "effective_at": _normalize_timestamp(self.effective_at).isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "TopupJobPayload":
        return cls(
            cadence=TopupCadence(str(payload["cadence"])),
            effective_at=datetime.fromisoformat(str(payload["effective_at"])),
        )


@dataclass(frozen=True)
class SyntheticTraderTickJobPayload:
    effective_at: datetime

    def to_payload(self) -> dict[str, str]:
        return {"effective_at": _normalize_timestamp(self.effective_at).isoformat()}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SyntheticTraderTickJobPayload":
        return cls(effective_at=datetime.fromisoformat(str(payload["effective_at"])))


@dataclass(frozen=True)
class IngestPlayersJobPayload:
    league: int = 9
    season: int = 2025

    def to_payload(self) -> dict[str, int]:
        return {"league": self.league, "season": self.season}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "IngestPlayersJobPayload":
        if "league" in payload and "season" in payload:
            return cls(league=int(payload["league"]), season=int(payload["season"]))
        return cls(league=9, season=int(payload.get("season", 2025)))


@dataclass(frozen=True)
class IngestFixturesJobPayload:
    league: int
    season: int
    from_date: date | None = None
    to_date: date | None = None

    def to_payload(self) -> dict[str, str | int]:
        payload: dict[str, str | int] = {
            "league": self.league,
            "season": self.season,
        }
        if self.from_date is not None:
            payload["from_date"] = self.from_date.isoformat()
        if self.to_date is not None:
            payload["to_date"] = self.to_date.isoformat()
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "IngestFixturesJobPayload":
        return cls(
            league=int(payload["league"]),
            season=int(payload["season"]),
            from_date=_optional_date(payload.get("from_date")),
            to_date=_optional_date(payload.get("to_date")),
        )


@dataclass(frozen=True)
class IngestPlayerStatsJobPayload:
    league: int = 9
    season: int = 2025
    stat_types: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"league": self.league, "season": self.season}
        if self.stat_types:
            payload["stat_types"] = list(self.stat_types)
        return payload

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "IngestPlayerStatsJobPayload":
        raw_stat_types = payload.get("stat_types", ())
        if raw_stat_types in (None, ""):
            stat_types = ()
        elif isinstance(raw_stat_types, str):
            stat_types = (raw_stat_types,)
        else:
            stat_types = tuple(str(stat_type) for stat_type in raw_stat_types)
        return cls(
            league=int(payload.get("league", 9)),
            season=int(payload.get("season", 2025)),
            stat_types=stat_types,
        )


@dataclass(frozen=True)
class IngestBet365OddsJobPayload:
    league: str | None = None

    def to_payload(self) -> dict[str, str]:
        return {} if self.league is None else {"league": self.league}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "IngestBet365OddsJobPayload":
        value = payload.get("league")
        return cls(league=None if value is None else str(value))


@dataclass(frozen=True)
class WorkerJob:
    job_type: JobType
    payload: Mapping[str, Any]
    attempt: int = 0

    def to_message(self) -> dict[str, Any]:
        return {
            "job_type": self.job_type.value,
            "payload": dict(self.payload),
            "attempt": self.attempt,
        }

    @classmethod
    def from_message(cls, message: Mapping[str, Any]) -> "WorkerJob":
        payload = message.get("payload", {})
        if not isinstance(payload, Mapping):
            raise TypeError("worker job payload must be a mapping")
        return cls(
            job_type=JobType(str(message["job_type"])),
            payload=payload,
            attempt=int(message.get("attempt", 0)),
        )

    @classmethod
    def topup(cls, payload: TopupJobPayload) -> "WorkerJob":
        return cls(job_type=JobType.APPLY_TOPUPS, payload=payload.to_payload())

    @classmethod
    def synthetic_trader_tick(cls, payload: SyntheticTraderTickJobPayload) -> "WorkerJob":
        return cls(job_type=JobType.SYNTHETIC_TRADER_TICK, payload=payload.to_payload())

    @classmethod
    def ingest_players(cls, payload: IngestPlayersJobPayload) -> "WorkerJob":
        return cls(job_type=JobType.INGEST_PLAYERS, payload=payload.to_payload())

    @classmethod
    def ingest_fixtures(cls, payload: IngestFixturesJobPayload) -> "WorkerJob":
        return cls(job_type=JobType.INGEST_FIXTURES, payload=payload.to_payload())

    @classmethod
    def ingest_player_stats(
        cls,
        payload: IngestPlayerStatsJobPayload,
    ) -> "WorkerJob":
        return cls(
            job_type=JobType.INGEST_PLAYER_STATS,
            payload=payload.to_payload(),
        )

    @classmethod
    def ingest_bet365_odds(cls, payload: IngestBet365OddsJobPayload) -> "WorkerJob":
        return cls(job_type=JobType.INGEST_BET365_ODDS, payload=payload.to_payload())

    def with_attempt(self, attempt: int) -> "WorkerJob":
        return WorkerJob(job_type=self.job_type, payload=self.payload, attempt=attempt)


@dataclass(frozen=True)
class JobExecutionResult:
    job_type: JobType
    handled_at: datetime
    successful_items: int
    skipped_items: int
    failed_items: int
    retryable_failures: int = 0


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(str(value))
