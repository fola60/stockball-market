from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

import redis


OPERATION_JOB_TYPES = {
    "INGEST_PLAYERS": "INGEST_PLAYERS",
    "INGEST_FIXTURES": "INGEST_FIXTURES",
    "INGEST_PLAYER_STATS": "INGEST_PLAYER_STATS",
    "IMPORT_MARKET_VALUES": "IMPORT_MARKET_VALUES",
    "SEED_PLAYER_SHARES": "SEED_PLAYER_SHARES",
    "INGEST_BETTING_MARKETS": "INGEST_BET365_ODDS",
    "INGEST_TWITTER_INJURIES": "INGEST_TWITTER_INJURIES",
    "APPLY_TOPUPS": "APPLY_TOPUPS",
    "TICK_SYNTHETIC_TRADERS": "SYNTHETIC_TRADER_TICK",
    "SPAWN_SYNTHETIC_TRADERS": "SPAWN_SYNTHETIC_TRADERS",
    "BOOTSTRAP_SYNTHETIC_PORTFOLIOS": "BOOTSTRAP_SYNTHETIC_PORTFOLIOS",
    "SET_SYNTHETIC_TRADER_STATUS": "SET_SYNTHETIC_TRADER_STATUS",
}


class DevOperationsRepository(Protocol):
    def create_run(self, run_id: UUID, operation_type: str, job_type: str, parameters: Mapping[str, Any]) -> dict[str, Any]: ...
    def mark_enqueue_failed(self, run_id: UUID, message: str) -> None: ...
    def list_runs(
        self,
        limit: int = 100,
        *,
        operation_type: str | None = None,
        exclude_operation_type: list[str] | None = None,
        status: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def get_run(self, run_id: UUID) -> dict[str, Any] | None: ...
    def summary(self) -> dict[str, Any]: ...
    def list_bots(self) -> list[dict[str, Any]]: ...
    def list_profiles(self) -> list[dict[str, Any]]: ...
    def get_bot_details(self, bot_id: UUID) -> dict[str, Any] | None: ...
    def list_trades(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        account_type: str | None = None,
        side: str | None = None,
    ) -> dict[str, Any]: ...
    def get_trade_details(self, trade_id: UUID) -> dict[str, Any] | None: ...


class JobPublisher(Protocol):
    def enqueue(self, message: Mapping[str, Any]) -> None: ...


class ProcessRegistry(Protocol):
    def snapshot(self) -> dict[str, Any]: ...
    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]: ...


class RedisJobPublisher:
    def __init__(self, redis_url: str, queue_name: str) -> None:
        self._queue_name = queue_name
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def enqueue(self, message: Mapping[str, Any]) -> None:
        self._client.rpush(self._queue_name, json.dumps(dict(message), sort_keys=True, separators=(",", ":")))


@dataclass(frozen=True)
class DevOperationsService:
    repository: DevOperationsRepository
    publisher: JobPublisher
    process_registry: ProcessRegistry | None = None

    def enqueue(self, operation_type: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        try:
            job_type = OPERATION_JOB_TYPES[operation_type]
        except KeyError as error:
            raise ValueError(f"unsupported operation type: {operation_type}") from error
        normalized = _normalize_parameters(operation_type, parameters)
        run_id = uuid4()
        run = self.repository.create_run(run_id, operation_type, job_type, normalized)
        try:
            self.publisher.enqueue(
                {"job_type": job_type, "payload": normalized, "attempt": 0, "operation_run_id": str(run_id)}
            )
        except Exception as error:
            self.repository.mark_enqueue_failed(run_id, f"failed to enqueue operation: {error}")
            raise
        return run


def _normalize_parameters(operation_type: str, values: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in values.items() if value is not None and value != ""}
    if operation_type in {"INGEST_PLAYERS", "INGEST_FIXTURES", "INGEST_PLAYER_STATS"}:
        result.setdefault("league", 9)
        result.setdefault("season", 2025)
    if operation_type == "TICK_SYNTHETIC_TRADERS":
        from datetime import UTC, datetime
        result.setdefault("effective_at", datetime.now(UTC).isoformat())
        result.setdefault("force_timing", False)
        tick_count = int(result.get("tick_count", 1))
        if tick_count < 1 or tick_count > 100:
            raise ValueError("tick count must be between 1 and 100")
        if tick_count > 1 and not result["force_timing"]:
            raise ValueError("repeated ticks require forced timing")
        result["tick_count"] = tick_count
        bot_ids = result.get("bot_ids", [])
        if len(bot_ids) > 500:
            raise ValueError("no more than 500 bots can be ticked at once")
        result["bot_ids"] = [str(UUID(str(bot_id))) for bot_id in bot_ids]
    if operation_type == "APPLY_TOPUPS":
        from datetime import UTC, datetime
        result.setdefault("effective_at", datetime.now(UTC).isoformat())
        result.setdefault("cadence", "WEEKLY")
        result.setdefault("synthetic_trader_amount", "100000.0000")
        try:
            amount = Decimal(str(result["synthetic_trader_amount"]))
        except InvalidOperation as error:
            raise ValueError("synthetic trader top-up amount must be numeric") from error
        if not amount.is_finite() or amount <= 0:
            raise ValueError("synthetic trader top-up amount must be greater than zero")
        result["synthetic_trader_amount"] = format(amount, "f")
    if operation_type == "SPAWN_SYNTHETIC_TRADERS":
        count = int(result.get("count", 0))
        if count < 1 or count > 500:
            raise ValueError("spawn count must be between 1 and 500")
        result["count"] = count
        result.setdefault("name_style", "PERSONA")
        result.setdefault("status", "ACTIVE")
        if not result.get("config_key") and not result.get("strategy_engine"):
            raise ValueError("config_key or strategy_engine is required")
        if result.get("strategy_engine") == "SOCIAL_SENTIMENT":
            raise ValueError("social sentiment is outside this portal's scope")
    if operation_type == "IMPORT_MARKET_VALUES" and not result.get("valuations_csv"):
        raise ValueError("valuations_csv is required")
    if operation_type == "BOOTSTRAP_SYNTHETIC_PORTFOLIOS":
        if not result.get("all_active_synthetic_bots") and not result.get("bot_ids"):
            raise ValueError("select all active bots or provide bot_ids")
        result.setdefault("dry_run", True)
    if operation_type == "SET_SYNTHETIC_TRADER_STATUS":
        if result.get("status") not in {"ACTIVE", "PAUSED", "RETIRED"}:
            raise ValueError("status must be ACTIVE, PAUSED, or RETIRED")
        if not result.get("bot_ids"):
            raise ValueError("bot_ids is required")
    return result
