from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .runtime_settings import RuntimeSettingsRegistry

_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SENSITIVE_PARTS = ("PASSWORD", "TOKEN", "SECRET", "DATABASE_URL", "USER_DATA_DIR")
_LIVE_SETTINGS = {
    "STOCKBALL_PLAYER_STATS_SCHEDULE_HOUR_UTC": "player_stats_schedule_hour_utc",
    "STOCKBALL_PLAYER_STATS_SCHEDULE_LEAGUE": "player_stats_schedule_league",
    "STOCKBALL_PLAYER_STATS_SCHEDULE_SEASON": "player_stats_schedule_season",
    "STOCKBALL_BET365_SCHEDULE_INTERVAL_MINUTES": "bet365_schedule_interval_minutes",
    "STOCKBALL_BET365_LIVE_SCHEDULE_INTERVAL_MINUTES": "bet365_live_schedule_interval_minutes",
    "STOCKBALL_TWITTER_INJURY_SCHEDULE_INTERVAL_MINUTES": "twitter_injury_schedule_interval_minutes",
}


class EnvironmentAuditRepository(Protocol):
    def record_admin_audit_event(
        self,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_key: str,
        before_value: Any,
        after_value: Any,
        reason: str,
    ) -> None: ...


@dataclass(frozen=True)
class EnvironmentDefinition:
    name: str
    default: str


class EnvironmentFileService:
    def __init__(
        self,
        env_path: Path,
        example_path: Path,
        audit_repository: EnvironmentAuditRepository,
        runtime_settings: RuntimeSettingsRegistry | None = None,
    ) -> None:
        self._env_path = env_path
        self._example_path = example_path
        self._audit_repository = audit_repository
        self._runtime_settings = runtime_settings
        self._lock = threading.Lock()

    def list(self) -> list[dict[str, Any]]:
        definitions = _parse_environment(self._example_path.read_text())
        configured = _parse_environment(self._env_path.read_text())
        names = sorted(set(definitions) | set(configured), key=lambda name: (_category(name), name))
        return [
            _serialize_environment(name, configured.get(name), definitions.get(name, ""))
            for name in names
        ]

    def update(self, name: str, value: str, *, actor: str, reason: str) -> dict[str, Any]:
        if not _NAME_PATTERN.fullmatch(name):
            raise ValueError("invalid environment variable name")
        normalized_reason = reason.strip()
        if len(normalized_reason) < 3:
            raise ValueError("a change reason of at least 3 characters is required")
        if "\n" in value or "\r" in value:
            raise ValueError("environment values cannot contain newlines")
        definitions = _parse_environment(self._example_path.read_text())
        configured = _parse_environment(self._env_path.read_text())
        if name not in definitions and name not in configured:
            raise ValueError(f"unknown application environment variable: {name}")
        _validate_value(name, value, definitions.get(name, ""))
        before = configured.get(name)
        with self._lock:
            _replace_environment_value(self._env_path, name, value)
        sensitive = _is_sensitive(name)
        self._audit_repository.record_admin_audit_event(
            actor=actor,
            action="ENVIRONMENT_UPDATED",
            target_type="ENVIRONMENT_VARIABLE",
            target_key=name,
            before_value="********" if sensitive and before else before,
            after_value="********" if sensitive and value else value,
            reason=normalized_reason,
        )
        runtime_key = _LIVE_SETTINGS.get(name)
        if runtime_key and self._runtime_settings is not None:
            self._runtime_settings.update(
                runtime_key,
                int(value),
                actor=actor,
                reason=normalized_reason,
            )
        return _serialize_environment(name, value, definitions.get(name, ""))


def _parse_environment(contents: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if _NAME_PATTERN.fullmatch(name.strip()):
            result[name.strip()] = value
    return result


def _replace_environment_value(path: Path, name: str, value: str) -> None:
    lines = path.read_text().splitlines()
    replacement = f"{name}={value}"
    for index, line in enumerate(lines):
        if line.startswith(f"{name}="):
            lines[index] = replacement
            break
    else:
        if lines and lines[-1]:
            lines.append("")
        lines.append(replacement)
    path.write_text("\n".join(lines) + "\n")


def _serialize_environment(name: str, configured: str | None, default: str) -> dict[str, Any]:
    sensitive = _is_sensitive(name)
    effective = default if configured is None else configured
    return {
        "name": name,
        "value": None if sensitive else effective,
        "configured": configured is not None,
        "has_value": bool(effective),
        "default_value": None if sensitive else default,
        "sensitive": sensitive,
        "category": _category(name),
        "services": _services(name),
        "value_type": _value_type(default or effective),
        "apply_mode": "next_scheduler_cycle" if name in _LIVE_SETTINGS else "service_recreation",
    }


def _is_sensitive(name: str) -> bool:
    return any(part in name for part in _SENSITIVE_PARTS)


def _category(name: str) -> str:
    if name.startswith("POSTGRES_") or name in {"DATABASE_URL", "STOCKBALL_DATABASE_POOL_SIZE"}:
        return "Database"
    if "TWITTER" in name:
        return "Injury intelligence"
    if "BET365" in name:
        return "Betting markets"
    if "FBREF" in name or "PLAYER_STATS" in name or "MARKET_VALUES" in name:
        return "Player data"
    if "PORT" in name or "BIND_ADDR" in name or name.startswith("NEXT_PUBLIC"):
        return "Networking"
    if "REDIS" in name or "QUEUE" in name or "CLAIM" in name:
        return "Queue and scheduling"
    if "BOOTSTRAP" in name:
        return "Development bootstrap"
    if "SOCIAL" in name:
        return "Social signals"
    return "Application"


def _services(name: str) -> list[str]:
    if name.startswith("POSTGRES_"):
        return ["postgres"]
    if name.startswith("NEXT_PUBLIC_") or name == "ADMIN_UI_PORT":
        return ["admin-ui"]
    if name.startswith("STOCKBALL_API_") or name == "API_PORT":
        return ["api"]
    if "TRADING_ENGINE" in name or name == "TRADING_ENGINE_PORT":
        return ["trading-engine", "api", "worker"]
    if name.startswith("STOCKBALL_WORKER_"):
        return ["worker", "scheduler"]
    if name.startswith("STOCKBALL_WEB_") or name == "WEB_PORT":
        return ["web"]
    if name.startswith("STOCKBALL_"):
        return ["api", "worker", "scheduler"]
    return ["compose"]


def _value_type(value: str) -> str:
    if value.lower() in {"true", "false"}:
        return "boolean"
    try:
        int(value)
        return "integer"
    except ValueError:
        pass
    try:
        float(value)
        return "number"
    except ValueError:
        return "string"


def _validate_value(name: str, value: str, default: str) -> None:
    value_type = _value_type(default) if default else "string"
    if value_type == "boolean" and value.lower() not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        raise ValueError(f"{name} must be a boolean")
    if value_type == "integer":
        int(value)
    if value_type == "number":
        float(value)
