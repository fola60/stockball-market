from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from .models import MarketValueMatchStatus, MarketValueRow, PlayerMatch

MATCHED_CONFIDENCE = Decimal("0.950")
CLUB_MATCH_CONFIDENCE = Decimal("0.850")
UNIQUE_NAME_MATCH_CONFIDENCE = Decimal("0.800")


_CLUB_ALIASES = {
    "arsenal": "arsenal",
    "arsenal football club": "arsenal",
    "aston villa": "aston villa",
    "aston villa football club": "aston villa",
    "association football club bournemouth": "bournemouth",
    "afc bournemouth": "bournemouth",
    "bournemouth": "bournemouth",
    "brentford": "brentford",
    "brentford football club": "brentford",
    "brighton": "brighton",
    "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton",
    "brighton and hove albion football club": "brighton",
    "burnley": "burnley",
    "burnley football club": "burnley",
    "chelsea": "chelsea",
    "chelsea football club": "chelsea",
    "crystal palace": "crystal palace",
    "crystal palace football club": "crystal palace",
    "everton": "everton",
    "everton football club": "everton",
    "fulham": "fulham",
    "fulham football club": "fulham",
    "leeds united": "leeds united",
    "leeds united association football club": "leeds united",
    "liverpool": "liverpool",
    "liverpool football club": "liverpool",
    "manchester city": "manchester city",
    "manchester city football club": "manchester city",
    "man city": "manchester city",
    "manchester united": "manchester united",
    "manchester united football club": "manchester united",
    "man united": "manchester united",
    "manchester utd": "manchester united",
    "man utd": "manchester united",
    "newcastle": "newcastle united",
    "newcastle united": "newcastle united",
    "newcastle united football club": "newcastle united",
    "nottingham": "nottingham forest",
    "nottingham forest": "nottingham forest",
    "nottingham forest football club": "nottingham forest",
    "nottm forest": "nottingham forest",
    "sunderland": "sunderland",
    "sunderland association football club": "sunderland",
    "tottenham": "tottenham hotspur",
    "tottenham hotspur": "tottenham hotspur",
    "tottenham hotspur football club": "tottenham hotspur",
    "west ham": "west ham united",
    "west ham united": "west ham united",
    "west ham united football club": "west ham united",
    "wolverhampton wanderers": "wolverhampton wanderers",
    "wolverhampton wanderers football club": "wolverhampton wanderers",
    "wolves": "wolverhampton wanderers",
}


@dataclass(frozen=True)
class PlayerCandidate:
    player_id: UUID
    display_name: str
    club: str | None
    date_of_birth: date | None
    nationality: str | None
    metadata: Mapping[str, Any]


def match_market_value_row(
    row: MarketValueRow,
    existing_ref_player_id: UUID | None,
    candidates: list[PlayerCandidate],
    source_name_occurrences: int | None = None,
) -> PlayerMatch:
    return match_player_identity(
        source_player_name=row.source_player_name,
        source_club=row.source_club,
        source_date_of_birth=row.source_date_of_birth,
        existing_ref_player_id=existing_ref_player_id,
        candidates=candidates,
        source_name_occurrences=source_name_occurrences,
    )


def match_player_identity(
    *,
    source_player_name: str | None,
    source_club: str | None,
    source_date_of_birth: date | None,
    existing_ref_player_id: UUID | None,
    candidates: list[PlayerCandidate],
    source_name_occurrences: int | None = None,
) -> PlayerMatch:
    if existing_ref_player_id is not None:
        return PlayerMatch(
            player_id=existing_ref_player_id,
            status=MarketValueMatchStatus.MATCHED,
            confidence=Decimal("1.000"),
            reason="existing_provider_ref",
        )

    name = normalize_name(source_player_name)
    if not name:
        return PlayerMatch(
            player_id=None,
            status=MarketValueMatchStatus.UNMATCHED,
            confidence=None,
            reason="missing_source_name",
        )

    name_matches = [
        candidate for candidate in candidates if normalize_name(candidate.display_name) == name
    ]
    if not name_matches:
        # A source can use the formal first name while FBref uses a nickname, or
        # omit/add a surname. Require a shared name token *and* two independent
        # facts before considering this spelling-variant path.
        club = normalize_club(source_club)
        if source_date_of_birth is not None and club:
            source_tokens = set(name.split())
            variant_matches = [
                candidate
                for candidate in candidates
                if candidate.date_of_birth == source_date_of_birth
                and (
                    normalize_club(candidate.club) == club
                    or normalize_club(_metadata_string(candidate.metadata, "team_name")) == club
                )
                and source_tokens.intersection(normalize_name(candidate.display_name).split())
            ]
            if len(variant_matches) == 1:
                return PlayerMatch(
                    player_id=variant_matches[0].player_id,
                    status=MarketValueMatchStatus.MATCHED,
                    confidence=MATCHED_CONFIDENCE,
                    reason="name_variant_date_of_birth_and_club",
                )
            if len(variant_matches) > 1:
                return PlayerMatch(
                    player_id=None,
                    status=MarketValueMatchStatus.AMBIGUOUS,
                    confidence=None,
                    reason="multiple_name_variant_date_of_birth_and_club_matches",
                )
        return PlayerMatch(
            player_id=None,
            status=MarketValueMatchStatus.UNMATCHED,
            confidence=None,
            reason="no_name_match",
        )

    if source_date_of_birth is not None:
        dob_matches = [
            candidate
            for candidate in name_matches
            if candidate.date_of_birth == source_date_of_birth
        ]
        if len(dob_matches) == 1:
            return PlayerMatch(
                player_id=dob_matches[0].player_id,
                status=MarketValueMatchStatus.MATCHED,
                confidence=MATCHED_CONFIDENCE,
                reason="name_and_date_of_birth",
            )
        if len(dob_matches) > 1:
            return PlayerMatch(
                player_id=None,
                status=MarketValueMatchStatus.AMBIGUOUS,
                confidence=None,
                reason="multiple_name_and_date_of_birth_matches",
            )

    club = normalize_club(source_club)
    if club:
        club_matches = [
            candidate
            for candidate in name_matches
            if normalize_club(candidate.club) == club
            or normalize_club(_metadata_string(candidate.metadata, "team_name")) == club
        ]
        if len(club_matches) == 1:
            return PlayerMatch(
                player_id=club_matches[0].player_id,
                status=MarketValueMatchStatus.MATCHED,
                confidence=CLUB_MATCH_CONFIDENCE,
                reason="name_and_club",
            )
        if len(club_matches) > 1:
            return PlayerMatch(
                player_id=None,
                status=MarketValueMatchStatus.AMBIGUOUS,
                confidence=None,
                reason="multiple_name_and_club_matches",
            )

    if len(name_matches) == 1 and source_name_occurrences == 1:
        return PlayerMatch(
            player_id=name_matches[0].player_id,
            status=MarketValueMatchStatus.MATCHED,
            confidence=UNIQUE_NAME_MATCH_CONFIDENCE,
            reason="unique_normalized_name",
        )

    if len(name_matches) == 1:
        return PlayerMatch(
            player_id=None,
            status=MarketValueMatchStatus.AMBIGUOUS,
            confidence=None,
            reason="name_only_match_requires_review",
        )

    return PlayerMatch(
        player_id=None,
        status=MarketValueMatchStatus.AMBIGUOUS,
        confidence=None,
        reason="multiple_name_matches",
    )


def normalize_name(value: str | None) -> str:
    if value is None:
        return ""
    normalized = _ascii(value).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def normalize_club(value: str | None) -> str:
    normalized = normalize_name(value)
    alias = _CLUB_ALIASES.get(normalized)
    if alias is not None:
        return alias
    suffixes = (" fc", " afc", " cf", " sc")
    for suffix in suffixes:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized.strip()


def _ascii(value: str) -> str:
    value = value.translate(
        str.maketrans(
            {
                "ø": "o",
                "Ø": "O",
                "ı": "i",
                "İ": "I",
                "đ": "d",
                "Đ": "D",
                "ł": "l",
                "Ł": "L",
                "ð": "d",
                "Ð": "D",
                "æ": "ae",
                "Æ": "Ae",
                "œ": "oe",
                "Œ": "Oe",
                "ß": "ss",
                "þ": "th",
                "Þ": "Th",
            }
        )
    )
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def _metadata_string(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    return str(value)
