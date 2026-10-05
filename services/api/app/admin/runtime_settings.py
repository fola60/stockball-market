from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


class RuntimeSettingsRepository(Protocol):
    def runtime_setting_values(self) -> dict[str, Any]: ...
    def set_runtime_setting(self, key: str, value: Any, *, actor: str, reason: str) -> None: ...
    def reset_runtime_setting(self, key: str, *, actor: str, reason: str) -> None: ...
    def list_admin_audit_events(self, limit: int = 50) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class RuntimeSettingDefinition:
    key: str
    label: str
    description: str
    category: str
    default: int
    minimum: int
    maximum: int
    unit: str | None = None
    apply_mode: str = "next_scheduler_cycle"

    def validate(self, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{self.label} must be an integer")
        if value < self.minimum:
            raise ValueError(f"{self.label} must be at least {self.minimum}")
        if value > self.maximum:
            raise ValueError(f"{self.label} must be at most {self.maximum}")
        return value


def runtime_setting_definitions() -> tuple[RuntimeSettingDefinition, ...]:
    return (
        RuntimeSettingDefinition("player_stats_schedule_hour_utc", "Player stats hour", "UTC hour for the daily player statistics import.", "Player data", _int_env("STOCKBALL_PLAYER_STATS_SCHEDULE_HOUR_UTC", 3), 0, 23, "UTC hour"),
        RuntimeSettingDefinition("player_stats_schedule_league", "Player stats league", "Provider league identifier used by the scheduled import.", "Player data", _int_env("STOCKBALL_PLAYER_STATS_SCHEDULE_LEAGUE", 9), 1, 1000),
        RuntimeSettingDefinition("player_stats_schedule_season", "Player stats season", "Season start year for the scheduled player statistics import; 0 follows the season in progress.", "Player data", _int_env("STOCKBALL_PLAYER_STATS_SCHEDULE_SEASON", 0), 0, 2100),
        RuntimeSettingDefinition("bet365_schedule_interval_minutes", "Pre-match odds interval", "Minutes between pre-match odds collection windows.", "Market data", _int_env("STOCKBALL_BET365_SCHEDULE_INTERVAL_MINUTES", 15), 1, 60, "minutes"),
        RuntimeSettingDefinition("bet365_live_schedule_interval_minutes", "Live odds interval", "Minutes between live odds collection windows.", "Market data", _int_env("STOCKBALL_BET365_LIVE_SCHEDULE_INTERVAL_MINUTES", 1), 1, 60, "minutes"),
        RuntimeSettingDefinition("twitter_injury_schedule_interval_minutes", "Injury intelligence interval", "Minutes between configured injury intelligence searches.", "Social data", _int_env("STOCKBALL_TWITTER_INJURY_SCHEDULE_INTERVAL_MINUTES", 5), 1, 1440, "minutes"),
    )


class RuntimeSettingsRegistry:
    def __init__(self, repository: RuntimeSettingsRepository) -> None:
        self._repository = repository
        self._definitions = {item.key: item for item in runtime_setting_definitions()}

    def list(self) -> list[dict[str, Any]]:
        stored = self._repository.runtime_setting_values()
        return [self._serialize(item, stored.get(item.key)) for item in self._definitions.values()]

    def values(self) -> dict[str, Any]:
        stored = self._repository.runtime_setting_values()
        return {key: stored.get(key, definition.default) for key, definition in self._definitions.items()}

    def update(self, key: str, value: Any, *, actor: str, reason: str) -> dict[str, Any]:
        definition = self._definition(key)
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("a change reason is required")
        if value is None:
            self._repository.reset_runtime_setting(key, actor=actor, reason=normalized_reason)
        else:
            self._repository.set_runtime_setting(key, definition.validate(value), actor=actor, reason=normalized_reason)
        stored = self._repository.runtime_setting_values()
        return self._serialize(definition, stored.get(key))

    def _definition(self, key: str) -> RuntimeSettingDefinition:
        try:
            return self._definitions[key]
        except KeyError as error:
            raise ValueError(f"unknown runtime setting: {key}") from error

    @staticmethod
    def _serialize(definition: RuntimeSettingDefinition, stored_value: Any | None) -> dict[str, Any]:
        overridden = stored_value is not None
        return {
            "key": definition.key,
            "label": definition.label,
            "description": definition.description,
            "category": definition.category,
            "value_type": "integer",
            "default_value": definition.default,
            "value": stored_value if overridden else definition.default,
            "source": "runtime" if overridden else "environment",
            "minimum": definition.minimum,
            "maximum": definition.maximum,
            "unit": definition.unit,
            "apply_mode": definition.apply_mode,
        }


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)
