from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import UUID

from .models import PlayerAlias, SourceAccountKind, TwitterSourceAccount
from .resolution import normalize_identity

DEFAULT_TRUST_WEIGHTS = {
    SourceAccountKind.OFFICIAL_CLUB: 1.0,
    SourceAccountKind.OFFICIAL_LEAGUE: 1.0,
    SourceAccountKind.PLAYER_OWNED: 1.0,
    SourceAccountKind.CURATED_JOURNALIST: 0.95,
    SourceAccountKind.FAN: 0.25,
}


@dataclass(frozen=True)
class RegisteredPlayerAlias:
    player_id: UUID
    alias: PlayerAlias
    manually_reviewed_at: datetime
    reviewed_by: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class TwitterInjuryRegistry:
    sources: tuple[TwitterSourceAccount, ...]
    player_aliases: tuple[RegisteredPlayerAlias, ...]


@dataclass(frozen=True)
class TwitterInjuryRegistrySyncResult:
    source_accounts: int
    player_aliases: int


class TwitterInjuryRegistryRepository(Protocol):
    def sync_registry(self, registry: TwitterInjuryRegistry) -> TwitterInjuryRegistrySyncResult: ...


def load_registry(path: Path) -> TwitterInjuryRegistry:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Twitter injury registry must be a JSON object")
    sources = tuple(_source(row) for row in _rows(payload, "sources"))
    aliases = tuple(_alias(row) for row in _rows(payload, "player_aliases"))
    if not sources:
        raise ValueError("Twitter injury registry must contain at least one manually reviewed source")
    return TwitterInjuryRegistry(sources=sources, player_aliases=aliases)


def _source(row: Mapping[str, Any]) -> TwitterSourceAccount:
    account_kind = SourceAccountKind(str(row["account_kind"]))
    reviewed_at = _reviewed_at(row)
    reviewed_by = _required_string(row, "reviewed_by")
    review_notes = _required_string(row, "review_notes")
    trust_weight = float(row.get("trust_weight", DEFAULT_TRUST_WEIGHTS[account_kind]))
    if not 0 < trust_weight <= 1:
        raise ValueError("source trust_weight must be greater than 0 and at most 1")
    if (
        account_kind
        in {
            SourceAccountKind.OFFICIAL_CLUB,
            SourceAccountKind.OFFICIAL_LEAGUE,
            SourceAccountKind.PLAYER_OWNED,
        }
        and trust_weight != 1.0
    ):
        raise ValueError("official and player-owned source trust_weight must be 1.0")
    if account_kind is SourceAccountKind.CURATED_JOURNALIST and trust_weight > 0.95:
        raise ValueError("curated journalist trust_weight cannot exceed its 0.95 baseline")
    if account_kind is SourceAccountKind.FAN and trust_weight > 0.4:
        raise ValueError("fan source trust_weight cannot exceed 0.4")
    return TwitterSourceAccount(
        id=None,
        twitter_user_id=_required_string(row, "twitter_user_id"),
        username=_required_string(row, "username").lstrip("@"),
        display_name=_required_string(row, "display_name"),
        account_kind=account_kind,
        trust_weight=trust_weight,
        enabled=bool(row.get("enabled", True)),
        manually_reviewed_at=reviewed_at,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        metadata=_mapping(row.get("metadata")),
    )


def _alias(row: Mapping[str, Any]) -> RegisteredPlayerAlias:
    alias_value = _required_string(row, "alias")
    alias_type = _required_string(row, "alias_type").upper()
    if alias_type not in {"NAME", "HANDLE", "NICKNAME"}:
        raise ValueError(f"unsupported player alias_type: {alias_type}")
    return RegisteredPlayerAlias(
        player_id=UUID(_required_string(row, "player_id")),
        alias=PlayerAlias(
            alias=alias_value,
            alias_type=alias_type,
            club_hint=_optional_string(row.get("club_hint")),
        ),
        manually_reviewed_at=_reviewed_at(row),
        reviewed_by=_required_string(row, "reviewed_by"),
        metadata={
            **_mapping(row.get("metadata")),
            "normalized_alias": normalize_identity(alias_value),
        },
    )


def _rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    rows = payload.get(key, [])
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError(f"Twitter injury registry {key} must be a list of objects")
    return list(rows)


def _reviewed_at(row: Mapping[str, Any]) -> datetime:
    raw_value = _required_string(row, "manually_reviewed_at")
    parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _required_string(row: Mapping[str, Any], key: str) -> str:
    value = str(row.get(key, "")).strip()
    if not value:
        raise ValueError(f"Twitter injury registry field {key} is required")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _mapping(value: object) -> Mapping[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
