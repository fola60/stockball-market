from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping
from uuid import UUID

Normalizer = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class OperationDefinition:
    operation_type: str
    job_type: str
    label: str
    normalizer: Normalizer = lambda values: None

    def normalize(self, values: Mapping[str, Any]) -> dict[str, Any]:
        normalized = {
            key: value for key, value in values.items() if value is not None and value != ""
        }
        self.normalizer(normalized)
        return normalized

    def capability(self) -> dict[str, str]:
        return {
            "operation_type": self.operation_type,
            "job_type": self.job_type,
            "label": self.label,
        }


def _ingestion(values: dict[str, Any]) -> None:
    values.setdefault("league", 9)
    values.setdefault("season", 2025)


def _tick(values: dict[str, Any]) -> None:
    values.setdefault("effective_at", datetime.now(UTC).isoformat())
    values.setdefault("force_timing", False)
    tick_count = int(values.get("tick_count", 1))
    if not 1 <= tick_count <= 100:
        raise ValueError("tick count must be between 1 and 100")
    if tick_count > 1 and not values["force_timing"]:
        raise ValueError("repeated ticks require forced timing")
    bot_ids = values.get("bot_ids", [])
    if len(bot_ids) > 500:
        raise ValueError("no more than 500 bots can be ticked at once")
    values["tick_count"] = tick_count
    values["bot_ids"] = [str(UUID(str(bot_id))) for bot_id in bot_ids]


def _topup(values: dict[str, Any]) -> None:
    values.setdefault("effective_at", datetime.now(UTC).isoformat())
    values.setdefault("cadence", "WEEKLY")
    values.setdefault("synthetic_trader_amount", "100000.0000")
    try:
        amount = Decimal(str(values["synthetic_trader_amount"]))
    except InvalidOperation as error:
        raise ValueError("synthetic trader top-up amount must be numeric") from error
    if not amount.is_finite() or amount <= 0:
        raise ValueError("synthetic trader top-up amount must be greater than zero")
    values["synthetic_trader_amount"] = format(amount, "f")


def _spawn(values: dict[str, Any]) -> None:
    count = int(values.get("count", 0))
    if not 1 <= count <= 500:
        raise ValueError("spawn count must be between 1 and 500")
    values["count"] = count
    values.setdefault("name_style", "PERSONA")
    values.setdefault("status", "ACTIVE")
    if not values.get("config_key") and not values.get("strategy_engine"):
        raise ValueError("config_key or strategy_engine is required")
    if values.get("strategy_engine") == "SOCIAL_SENTIMENT":
        raise ValueError("social sentiment is outside this portal's scope")


def _market_values(values: dict[str, Any]) -> None:
    if not values.get("valuations_csv"):
        raise ValueError("valuations_csv is required")


def _social_feeds(values: dict[str, Any]) -> None:
    provider = str(values.get("provider", "ALL")).upper()
    if provider not in {"ALL", "RSS", "BLUESKY", "MASTODON"}:
        raise ValueError("social provider must be ALL, RSS, BLUESKY, or MASTODON")
    limit = int(values.get("limit", 100))
    if not 1 <= limit <= 500:
        raise ValueError("social feed limit must be between 1 and 500")
    values["provider"] = provider
    values["limit"] = limit


def _bootstrap(values: dict[str, Any]) -> None:
    if not values.get("all_active_synthetic_bots") and not values.get("bot_ids"):
        raise ValueError("select all active bots or provide bot_ids")
    values.setdefault("dry_run", True)


def _set_status(values: dict[str, Any]) -> None:
    if values.get("status") not in {"ACTIVE", "PAUSED", "RETIRED"}:
        raise ValueError("status must be ACTIVE, PAUSED, or RETIRED")
    if not values.get("bot_ids"):
        raise ValueError("bot_ids is required")


def _definition(
    operation_type: str,
    job_type: str | None = None,
    *,
    normalizer: Normalizer = lambda values: None,
) -> OperationDefinition:
    return OperationDefinition(
        operation_type=operation_type,
        job_type=job_type or operation_type,
        label=operation_type.replace("_", " ").title(),
        normalizer=normalizer,
    )


OPERATION_DEFINITIONS = tuple(
    [
        _definition("INGEST_PLAYERS", normalizer=_ingestion),
        _definition("INGEST_FIXTURES", normalizer=_ingestion),
        _definition("INGEST_PLAYER_STATS", normalizer=_ingestion),
        _definition("IMPORT_MARKET_VALUES", normalizer=_market_values),
        _definition("SEED_PLAYER_SHARES"),
        _definition("INGEST_BETTING_MARKETS", "INGEST_BET365_ODDS"),
        _definition("INGEST_TWITTER_INJURIES"),
        _definition("INGEST_SOCIAL_FEEDS", normalizer=_social_feeds),
        _definition("APPLY_TOPUPS", normalizer=_topup),
        _definition("TICK_SYNTHETIC_TRADERS", "SYNTHETIC_TRADER_TICK", normalizer=_tick),
        _definition("SPAWN_SYNTHETIC_TRADERS", normalizer=_spawn),
        _definition("BOOTSTRAP_SYNTHETIC_PORTFOLIOS", normalizer=_bootstrap),
        _definition("SET_SYNTHETIC_TRADER_STATUS", normalizer=_set_status),
    ]
)
OPERATIONS = {definition.operation_type: definition for definition in OPERATION_DEFINITIONS}


def operation_definition(operation_type: str) -> OperationDefinition:
    try:
        return OPERATIONS[operation_type]
    except KeyError as error:
        raise ValueError(f"unsupported operation type: {operation_type}") from error
