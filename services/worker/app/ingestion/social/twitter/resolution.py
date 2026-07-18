from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from uuid import UUID

from .models import (
    PlayerIdentityCandidate,
    PlayerResolution,
    PlayerResolutionStatus,
)


def normalize_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = normalized.casefold().replace("_", " ")
    return " ".join(re.sub(r"[^a-z0-9@ ]+", " ", normalized).split())


class PlayerResolver:
    def __init__(self, candidates: list[PlayerIdentityCandidate]) -> None:
        self._candidates = tuple(candidates)
        self._aliases: dict[str, list[tuple[PlayerIdentityCandidate, str, str | None]]] = (
            defaultdict(list)
        )
        for candidate in candidates:
            self._aliases[normalize_identity(candidate.display_name)].append(
                (candidate, candidate.display_name, candidate.club)
            )
            for alias in candidate.aliases:
                self._aliases[normalize_identity(alias.alias)].append(
                    (candidate, alias.alias, alias.club_hint or candidate.club)
                )

    def resolve(self, text: str, source_club_hint: str | None = None) -> PlayerResolution:
        normalized_text = f" {normalize_identity(text)} "
        matches: dict[UUID, tuple[PlayerIdentityCandidate, set[str], set[str]]] = {}
        for normalized_alias, alias_rows in self._aliases.items():
            if not normalized_alias or f" {normalized_alias} " not in normalized_text:
                continue
            for candidate, raw_alias, club_hint in alias_rows:
                row = matches.setdefault(candidate.player_id, (candidate, set(), set()))
                row[1].add(raw_alias)
                if club_hint:
                    row[2].add(normalize_identity(club_hint))

        if not matches:
            return PlayerResolution(
                status=PlayerResolutionStatus.UNRESOLVED,
                player_id=None,
                candidate_player_ids=(),
                matched_aliases=(),
                reason="no_exact_alias_boundary_match",
            )

        if len(matches) == 1:
            player_id, (_, aliases, _) = next(iter(matches.items()))
            return PlayerResolution(
                status=PlayerResolutionStatus.RESOLVED,
                player_id=player_id,
                candidate_player_ids=(player_id,),
                matched_aliases=tuple(sorted(aliases)),
                reason="unique_exact_alias_match",
            )

        normalized_club_hint = (
            None if source_club_hint is None else normalize_identity(source_club_hint)
        )
        club_matches: list[tuple[UUID, set[str]]] = []
        if normalized_club_hint:
            for player_id, (_, aliases, club_hints) in matches.items():
                if normalized_club_hint in club_hints:
                    club_matches.append((player_id, aliases))
        if len(club_matches) == 1:
            player_id, aliases = club_matches[0]
            return PlayerResolution(
                status=PlayerResolutionStatus.RESOLVED,
                player_id=player_id,
                candidate_player_ids=tuple(sorted(matches, key=str)),
                matched_aliases=tuple(sorted(aliases)),
                reason="source_club_hint_disambiguated",
            )

        aliases = {alias for _, candidate_aliases, _ in matches.values() for alias in candidate_aliases}
        return PlayerResolution(
            status=PlayerResolutionStatus.AMBIGUOUS,
            player_id=None,
            candidate_player_ids=tuple(sorted(matches, key=str)),
            matched_aliases=tuple(sorted(aliases)),
            reason="multiple_exact_alias_matches",
        )

