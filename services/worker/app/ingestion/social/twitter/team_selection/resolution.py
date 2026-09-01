from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from ..resolution import normalize_identity
from .models import (
    TeamIdentityCandidate,
    TeamResolution,
    TeamResolutionStatus,
)


class TeamResolver:
    """Resolve reviewed team names without fuzzy or partial-name guessing."""

    def __init__(self, candidates: list[TeamIdentityCandidate]) -> None:
        self._aliases: dict[str, list[tuple[TeamIdentityCandidate, str]]] = defaultdict(list)
        for candidate in candidates:
            for alias in (candidate.display_name, *candidate.aliases):
                normalized = normalize_identity(alias)
                if normalized:
                    self._aliases[normalized].append((candidate, alias))

    def resolve(self, text: str, source_team_hint: str | None = None) -> TeamResolution:
        normalized_text = f" {normalize_identity(text)} "
        matches: dict[UUID, tuple[TeamIdentityCandidate, set[str]]] = {}
        for normalized_alias, alias_rows in self._aliases.items():
            if f" {normalized_alias} " not in normalized_text:
                continue
            for candidate, raw_alias in alias_rows:
                row = matches.setdefault(candidate.team_id, (candidate, set()))
                row[1].add(raw_alias)

        hint_matches = self._resolve_hint(source_team_hint)
        if not matches:
            if len(hint_matches) == 1:
                candidate, alias = hint_matches[0]
                return TeamResolution(
                    status=TeamResolutionStatus.RESOLVED,
                    team_id=candidate.team_id,
                    candidate_team_ids=(candidate.team_id,),
                    matched_aliases=(alias,),
                    reason="reviewed_source_team_hint",
                )
            return TeamResolution(
                status=(
                    TeamResolutionStatus.AMBIGUOUS
                    if len(hint_matches) > 1
                    else TeamResolutionStatus.UNRESOLVED
                ),
                team_id=None,
                candidate_team_ids=tuple(
                    sorted((candidate.team_id for candidate, _ in hint_matches), key=str)
                ),
                matched_aliases=tuple(sorted({alias for _, alias in hint_matches})),
                reason=(
                    "ambiguous_source_team_hint"
                    if len(hint_matches) > 1
                    else "no_exact_team_alias_boundary_match"
                ),
            )

        if len(matches) == 1:
            team_id, (_, aliases) = next(iter(matches.items()))
            return TeamResolution(
                status=TeamResolutionStatus.RESOLVED,
                team_id=team_id,
                candidate_team_ids=(team_id,),
                matched_aliases=tuple(sorted(aliases)),
                reason="unique_exact_team_alias_match",
            )

        hinted_ids = {candidate.team_id for candidate, _ in hint_matches}
        disambiguated = hinted_ids.intersection(matches)
        if len(disambiguated) == 1:
            team_id = next(iter(disambiguated))
            return TeamResolution(
                status=TeamResolutionStatus.RESOLVED,
                team_id=team_id,
                candidate_team_ids=tuple(sorted(matches, key=str)),
                matched_aliases=tuple(sorted(matches[team_id][1])),
                reason="reviewed_source_team_hint_disambiguated",
            )

        return TeamResolution(
            status=TeamResolutionStatus.AMBIGUOUS,
            team_id=None,
            candidate_team_ids=tuple(sorted(matches, key=str)),
            matched_aliases=tuple(
                sorted({alias for _, aliases in matches.values() for alias in aliases})
            ),
            reason="multiple_exact_team_alias_matches",
        )

    def _resolve_hint(
        self,
        source_team_hint: str | None,
    ) -> list[tuple[TeamIdentityCandidate, str]]:
        if not source_team_hint:
            return []
        return list(self._aliases.get(normalize_identity(source_team_hint), ()))
