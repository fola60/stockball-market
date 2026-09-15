from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from ..injuries.resolution import (
    PlayerIdentityCandidate,
    PlayerResolution,
    PlayerResolutionStatus,
    PlayerResolver,
    normalize_identity,
)

_CLUB_ALIASES = {
    "arsenal": ("arsenal", "arsenal fc", "gunners", "afc"),
    "aston villa": ("aston villa", "villa", "avfc"),
    "bournemouth": ("bournemouth", "afc bournemouth", "cherries"),
    "brentford": ("brentford", "brentford fc", "bees"),
    "brighton": ("brighton", "brighton and hove albion", "seagulls", "bhafc"),
    "burnley": ("burnley", "burnley fc", "clarets"),
    "chelsea": ("chelsea", "chelsea fc", "cfc"),
    "crystal palace": ("crystal palace", "palace", "eagles", "cpfc"),
    "everton": ("everton", "everton fc", "toffees", "efc"),
    "fulham": ("fulham", "fulham fc", "cottagers", "ffc"),
    "ipswich town": ("ipswich town", "ipswich", "tractor boys", "itfc"),
    "leeds united": ("leeds united", "leeds", "lufc"),
    "liverpool": ("liverpool", "liverpool fc", "lfc", "reds"),
    "manchester city": ("manchester city", "man city", "city", "mcfc"),
    "manchester utd": (
        "manchester united",
        "manchester utd",
        "man united",
        "man utd",
        "united",
        "mufc",
    ),
    "newcastle": ("newcastle united", "newcastle", "magpies", "nufc"),
    "nottingham": ("nottingham forest", "nottingham", "forest", "nffc"),
    "sunderland": ("sunderland", "sunderland afc", "black cats", "safc"),
    "tottenham": ("tottenham hotspur", "tottenham", "spurs", "thfc"),
    "west ham": ("west ham united", "west ham", "hammers", "whufc"),
    "wolves": ("wolverhampton wanderers", "wolverhampton", "wolves", "wwfc"),
}
_UNITED_EXCLUSIONS = ("united kingdom", "united nations", "united states")


@dataclass(frozen=True)
class SocialResolution:
    player: PlayerResolution
    team_name: str | None


class SocialPlayerResolver:
    """Permissive resolver used for sentiment and attention observations only."""

    def __init__(self, candidates: Sequence[PlayerIdentityCandidate]) -> None:
        self._candidates = tuple(candidates)
        self._strict = PlayerResolver(list(candidates))
        self._global_partial = _partial_index(candidates)
        self._club_partial: dict[str, dict[str, set[UUID]]] = {}
        self._candidate_by_id = {candidate.player_id: candidate for candidate in candidates}
        grouped: dict[str, list[PlayerIdentityCandidate]] = defaultdict(list)
        for candidate in candidates:
            if candidate.club:
                grouped[normalize_identity(candidate.club)].append(candidate)
        for club, players in grouped.items():
            self._club_partial[club] = _partial_index(players)
        self._club_names = {
            normalize_identity(candidate.club): candidate.club
            for candidate in candidates
            if candidate.club
        }

    def resolve(self, text: str, source_club_hint: str | None = None) -> SocialResolution:
        team_name = self.resolve_team(text, source_club_hint)
        strict = self.resolve_strict(text, team_name or source_club_hint)
        if strict.status is not PlayerResolutionStatus.UNRESOLVED:
            return SocialResolution(strict, team_name)

        normalized_text = f" {normalize_identity(text)} "
        global_matches, global_aliases = _match_partial_names(
            normalized_text, self._global_partial
        )
        if global_matches:
            return SocialResolution(
                self._partial_resolution(global_matches, global_aliases, "globally_unique_name"),
                team_name,
            )

        if team_name:
            club_key = normalize_identity(team_name)
            club_matches, club_aliases = _match_partial_names(
                normalized_text, self._club_partial.get(club_key, {})
            )
            if club_matches:
                return SocialResolution(
                    self._partial_resolution(
                        club_matches,
                        club_aliases,
                        "club_context_unique_name",
                    ),
                    team_name,
                )
        return SocialResolution(strict, team_name)

    def resolve_strict(
        self, text: str, source_club_hint: str | None = None
    ) -> PlayerResolution:
        """Resolve only full names and reviewed aliases for injury evidence."""
        return self._strict.resolve(text, source_club_hint)

    def resolve_team(self, text: str, source_club_hint: str | None = None) -> str | None:
        normalized_text = normalize_identity(text)
        searchable = f" {normalized_text} "
        matches: list[tuple[int, str]] = []
        for configured_club, aliases in _CLUB_ALIASES.items():
            actual_club = self._club_names.get(configured_club)
            if actual_club is None:
                continue
            for alias in aliases:
                normalized_alias = normalize_identity(alias)
                if (
                    normalized_alias == "united"
                    and any(value in normalized_text for value in _UNITED_EXCLUSIONS)
                ):
                    continue
                if f" {normalized_alias} " in searchable:
                    matches.append((len(normalized_alias.split()), actual_club))
        if matches:
            best_specificity = max(score for score, _ in matches)
            best = {club for score, club in matches if score == best_specificity}
            if len(best) == 1:
                return next(iter(best))
        if source_club_hint:
            return self._club_names.get(
                normalize_identity(source_club_hint), source_club_hint
            )
        return None

    def _partial_resolution(
        self,
        player_ids: set[UUID],
        aliases: set[str],
        reason: str,
    ) -> PlayerResolution:
        ordered_ids = tuple(sorted(player_ids, key=str))
        if len(ordered_ids) == 1:
            return PlayerResolution(
                status=PlayerResolutionStatus.RESOLVED,
                player_id=ordered_ids[0],
                candidate_player_ids=ordered_ids,
                matched_aliases=tuple(sorted(aliases)),
                reason=reason,
            )
        return PlayerResolution(
            status=PlayerResolutionStatus.AMBIGUOUS,
            player_id=None,
            candidate_player_ids=ordered_ids,
            matched_aliases=tuple(sorted(aliases)),
            reason=f"multiple_{reason}_matches",
        )


def _partial_index(
    candidates: Sequence[PlayerIdentityCandidate],
) -> dict[str, set[UUID]]:
    indexed: dict[str, set[UUID]] = defaultdict(set)
    for candidate in candidates:
        parts = normalize_identity(candidate.display_name).split()
        if not parts:
            continue
        indexed[parts[0]].add(candidate.player_id)
        indexed[parts[-1]].add(candidate.player_id)
    return dict(indexed)


def _match_partial_names(
    normalized_text: str,
    index: dict[str, set[UUID]],
) -> tuple[set[UUID], set[str]]:
    matched_players: set[UUID] = set()
    matched_aliases: set[str] = set()
    for name, player_ids in index.items():
        if len(player_ids) != 1 or f" {name} " not in normalized_text:
            continue
        matched_players.update(player_ids)
        matched_aliases.add(name)
    return matched_players, matched_aliases
