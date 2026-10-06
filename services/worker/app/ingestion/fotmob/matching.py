"""Resolve provider identities with the market-value and FBref player matching rules."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable
from uuid import UUID

from app.ingestion.market_values.matching import (
    PlayerCandidate,
    match_player_identity,
    normalize_name,
)
from app.ingestion.market_values.models import MarketValueMatchStatus, PlayerMatch


@dataclass(frozen=True)
class FotMobIdentity:
    provider_player_id: str
    name: str
    club: str


def source_name_counts(identities: Iterable[FotMobIdentity]) -> dict[str, int]:
    """Count distinct source IDs, not repeated match appearances."""
    ids_by_name: dict[str, set[str]] = defaultdict(set)
    for identity in identities:
        name = normalize_name(identity.name)
        if name:
            ids_by_name[name].add(identity.provider_player_id)
    return {name: len(ids) for name, ids in ids_by_name.items()}


def resolve_identity(
    evidence: list[FotMobIdentity],
    *,
    candidates: list[PlayerCandidate],
    name_counts: dict[str, int],
    date_of_birth: date | None = None,
    trusted_ref: UUID | None = None,
) -> PlayerMatch:
    if trusted_ref is not None:
        return match_player_identity(
            source_player_name=evidence[0].name,
            source_club=evidence[0].club,
            source_date_of_birth=date_of_birth,
            existing_ref_player_id=trusted_ref,
            candidates=candidates,
        )

    decisions = [
        match_player_identity(
            source_player_name=item.name,
            source_club=item.club,
            source_date_of_birth=date_of_birth,
            existing_ref_player_id=None,
            candidates=candidates,
            source_name_occurrences=name_counts.get(normalize_name(item.name), 0),
        )
        for item in evidence
    ]
    matched = {decision.player_id for decision in decisions if decision.player_id is not None}
    if len(matched) > 1:
        return PlayerMatch(
            None, MarketValueMatchStatus.AMBIGUOUS, None, "conflicting_name_and_club_evidence"
        )
    if matched:
        strongest = max(
            (decision for decision in decisions if decision.player_id is not None),
            key=lambda decision: decision.confidence or 0,
        )
        return strongest
    if any(decision.status is MarketValueMatchStatus.AMBIGUOUS for decision in decisions):
        return PlayerMatch(None, MarketValueMatchStatus.AMBIGUOUS, None, "ambiguous_name_or_club")
    return PlayerMatch(None, MarketValueMatchStatus.UNMATCHED, None, "no_name_match")
