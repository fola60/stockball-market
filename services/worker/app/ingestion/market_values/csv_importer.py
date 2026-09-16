from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .models import MarketValuePlayerProfile, MarketValueRow

DEFAULT_SOURCE = "transfermarkt_csv"
DEFAULT_CURRENCY = "EUR"


class TransfermarktCsvMarketValueReader:
    def read(
        self,
        valuations_csv_path: Path,
        players_csv_path: Path | None = None,
        source: str = DEFAULT_SOURCE,
        currency: str = DEFAULT_CURRENCY,
    ) -> list[MarketValueRow]:
        profiles = self._read_profiles(players_csv_path)
        latest_by_player: dict[str, MarketValueRow] = {}
        with valuations_csv_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                source_player_id = _required(row, "player_id")
                value = _decimal(row.get("market_value_in_eur"))
                if value is None or value <= 0:
                    continue
                observed_at = _datetime(row.get("date"))
                profile = profiles.get(source_player_id)
                raw_payload: dict[str, Any] = {"valuation": dict(row)}
                if profile is not None:
                    raw_payload["player_profile"] = dict(profile.raw_payload)

                market_value = MarketValueRow(
                    source=source,
                    source_player_id=source_player_id,
                    source_player_name=_coalesce(profile.display_name if profile else None, row.get("player_name")),
                    source_club=_coalesce(
                        profile.club if profile else None,
                        row.get("current_club_name"),
                    ),
                    source_date_of_birth=profile.date_of_birth if profile else None,
                    source_nationality=profile.nationality if profile else None,
                    source_url=profile.source_url if profile else None,
                    value=value,
                    currency=currency,
                    observed_at=observed_at,
                    raw_payload=raw_payload,
                )
                existing = latest_by_player.get(source_player_id)
                if existing is None or market_value.observed_at > existing.observed_at:
                    latest_by_player[source_player_id] = market_value

        return list(latest_by_player.values())

    def _read_profiles(
        self,
        players_csv_path: Path | None,
    ) -> dict[str, MarketValuePlayerProfile]:
        if players_csv_path is None:
            return {}

        profiles: dict[str, MarketValuePlayerProfile] = {}
        with players_csv_path.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                source_player_id = _required(row, "player_id")
                profiles[source_player_id] = MarketValuePlayerProfile(
                    source_player_id=source_player_id,
                    display_name=_optional(row.get("name")),
                    club=_optional(row.get("current_club_name")),
                    date_of_birth=_date(row.get("date_of_birth")),
                    nationality=_optional(row.get("country_of_citizenship")),
                    source_url=_optional(row.get("url")),
                    raw_payload=dict(row),
                )
        return profiles


def _required(row: Mapping[str, str | None], key: str) -> str:
    value = _optional(row.get(key))
    if value is None:
        raise ValueError(f"required CSV column missing or empty: {key}")
    return value


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _coalesce(*values: str | None) -> str | None:
    for value in values:
        normalized = _optional(value)
        if normalized is not None:
            return normalized
    return None


def _decimal(value: str | None) -> Decimal | None:
    normalized = _optional(value)
    if normalized is None:
        return None
    return Decimal(normalized)


def _date(value: str | None) -> date | None:
    normalized = _optional(value)
    if normalized is None:
        return None
    return date.fromisoformat(normalized[:10])


def _datetime(value: str | None) -> datetime:
    parsed_date = _date(value)
    if parsed_date is None:
        raise ValueError("market value row must include a date")
    return datetime(
        parsed_date.year,
        parsed_date.month,
        parsed_date.day,
        tzinfo=UTC,
    )
