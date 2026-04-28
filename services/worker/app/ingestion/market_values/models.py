from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID


class MarketValueMatchStatus(StrEnum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class MarketValuePlayerProfile:
    source_player_id: str
    display_name: str | None
    club: str | None
    date_of_birth: date | None
    nationality: str | None
    source_url: str | None
    raw_payload: Mapping[str, Any]


@dataclass(frozen=True)
class MarketValueRow:
    source: str
    source_player_id: str
    source_player_name: str | None
    source_club: str | None
    source_date_of_birth: date | None
    source_nationality: str | None
    source_url: str | None
    value: Decimal
    currency: str
    observed_at: datetime
    raw_payload: Mapping[str, Any]


@dataclass(frozen=True)
class PlayerMatch:
    player_id: UUID | None
    status: MarketValueMatchStatus
    confidence: Decimal | None
    reason: str


@dataclass(frozen=True)
class MarketValueImportRow:
    market_value: MarketValueRow
    match: PlayerMatch


@dataclass(frozen=True)
class MarketValueImportResult:
    batch_id: UUID
    imported_rows: int
    matched_rows: int
    ambiguous_rows: int
    unmatched_rows: int
    rejected_rows: int
