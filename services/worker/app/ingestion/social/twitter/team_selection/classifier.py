from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Protocol

from ..models import SourceAccountKind, TwitterSourceAccount
from .models import (
    TeamSelectionClassification,
    TeamSelectionEventKind,
    TeamSelectionEvidencePhase,
    TeamSelectionSignal,
)


class TeamSelectionClassifier(Protocol):
    def classify(
        self,
        text: str,
        source: TwitterSourceAccount,
        observed_at: datetime,
        fixture_starts_at: datetime | None = None,
    ) -> TeamSelectionClassification: ...


_EXPECTED_STARTER_RULES = {
    "expected_to_start": r"\bexpected to start\b",
    "set_to_start": r"\bset to start\b",
    "likely_to_start": r"\blikely to start\b",
    "in_line_to_start": r"\bin line to start\b",
    "could_start": r"\bcould start\b",
    "predicted_lineup": r"\bpredicted (?:lineup|xi)\b",
}
_STARTER_RULES = {
    "starts": r"\bstarts\b",
    "starting_xi": r"\b(?:named in|in) (?:the )?starting (?:lineup|xi)\b",
    "lineup_starter": r"\blineup confirmed\b.{0,80}\bstart(?:s|ing)\b",
}
_BENCH_RULES = {
    "on_bench": r"\bon (?:the )?bench\b",
    "among_substitutes": r"\b(?:named |is )?(?:among|with) (?:the )?substitutes\b",
    "drops_to_bench": r"\bdrops? to (?:the )?bench\b",
    "benched": r"\bbenched\b",
}
_SQUAD_INCLUSION_RULES = {
    "included_in_squad": (
        r"\bincluded in (?:the )?(?:[a-z0-9'-]+ ){0,3}(?:matchday )?squad\b"
    ),
    "named_in_squad": (
        r"\bnamed in (?:the )?(?:[a-z0-9'-]+ ){0,3}(?:matchday )?squad\b"
    ),
    "in_matchday_squad": r"\bin (?:the )?matchday squad\b",
    "travels_with_squad": r"\btravels? with (?:the )?squad\b",
}
_SQUAD_EXCLUSION_RULES = {
    "not_in_squad": r"\bnot in (?:the )?(?:matchday )?squad\b",
    "not_included_in_squad": (
        r"\bnot included in (?:the )?(?:[a-z0-9'-]+ ){0,3}(?:matchday )?squad\b"
    ),
    "not_named_in_squad": (
        r"\bnot named in (?:the )?(?:[a-z0-9'-]+ ){0,3}(?:matchday )?squad\b"
    ),
    "omitted_from_squad": r"\bomitted from (?:the )?(?:matchday )?squad\b",
    "left_out": r"\bleft out of (?:the )?(?:matchday )?squad\b",
    "misses_out": r"\bmisses out on (?:the )?(?:matchday )?squad\b",
    "not_selected": r"\bnot selected\b",
}
_ROTATION_RULES = {
    "rested": r"\brested\b",
    "given_rest": r"\bgiven (?:a )?rest\b",
    "rotated": r"\brotated\b",
    "rotation": r"\b(?:squad|team|lineup) rotation\b",
}
_POSITION_RULES = {
    "starts_at": r"\bstarts? (?:at|as) (?:a |the )?{role}\b",
    "deployed_as": r"\bdeployed as (?:a |the )?{role}\b",
    "moves_to": r"\bmoves? (?:into|to) (?:a |the )?{role}\b",
    "shifted_to": r"\bshifted to (?:a |the )?{role}\b",
    "playing_as": r"\bplaying as (?:a |the )?{role}\b",
}
_CAPTAINCY_RULES = {
    "captains": r"\bcaptains? (?:the )?(?:side|team|club)\b",
    "named_captain": r"\bnamed (?:as )?captain\b",
    "wears_armband": r"\bwears? (?:the )?(?:captain'?s )?armband\b",
    "takes_armband": r"\btakes? (?:the )?armband\b",
}
_GOALKEEPER_RULES = {
    "goalkeeper_change": r"\bgoalkeeper change\b",
    "starts_in_goal": r"\bstarts? in goal\b",
    "replaces_in_goal": r"\breplaces? .{1,60} in goal\b",
    "between_posts": r"\bbetween the posts\b",
}
_UNCERTAINTY = re.compile(
    r"\b(?:reportedly|unconfirmed|rumou?red|possibly|perhaps|appears|seems|could|may|might)\b",
    re.IGNORECASE,
)
_START_NEGATION = re.compile(
    r"\b(?:not|unlikely|isn'?t|won'?t|will not)\s+(?:be )?(?:expected to )?start\b",
    re.IGNORECASE,
)
_BENCH_NEGATION = re.compile(r"\bnot on (?:the )?bench\b", re.IGNORECASE)
_SQUAD_INCLUSION_NEGATION = re.compile(
    r"\bnot (?:included|named) in (?:the )?(?:[a-z0-9'-]+ ){0,3}"
    r"(?:matchday )?squad\b",
    re.IGNORECASE,
)
_ROLES = (
    "goalkeeper",
    "left back",
    "right back",
    "centre back",
    "center back",
    "wing back",
    "defensive midfield",
    "central midfield",
    "attacking midfield",
    "midfield",
    "left wing",
    "right wing",
    "winger",
    "number 10",
    "false nine",
    "centre forward",
    "center forward",
    "striker",
)
_BASE_CONFIDENCE = {
    TeamSelectionEventKind.EXPECTED_STARTER: 0.78,
    TeamSelectionEventKind.LINEUP_STARTER: 0.98,
    TeamSelectionEventKind.BENCH: 0.97,
    TeamSelectionEventKind.SQUAD_INCLUSION: 0.94,
    TeamSelectionEventKind.SQUAD_EXCLUSION: 0.95,
    TeamSelectionEventKind.RESTED_OR_ROTATED: 0.90,
    TeamSelectionEventKind.POSITIONAL_ROLE_CHANGE: 0.88,
    TeamSelectionEventKind.CAPTAINCY: 0.96,
    TeamSelectionEventKind.GOALKEEPER_CHANGE: 0.94,
}


class RuleBasedTeamSelectionClassifier:
    """Classify explicit selection language without external model calls."""

    def classify(
        self,
        text: str,
        source: TwitterSourceAccount,
        observed_at: datetime,
        fixture_starts_at: datetime | None = None,
    ) -> TeamSelectionClassification:
        normalized = " ".join(text.split())
        uncertain = bool(_UNCERTAINTY.search(normalized))
        official = source.account_kind in {
            SourceAccountKind.OFFICIAL_CLUB,
            SourceAccountKind.OFFICIAL_LEAGUE,
        }
        aggregate_only = source.account_kind.is_aggregate_only
        matches: list[
            tuple[TeamSelectionEventKind, TeamSelectionEvidencePhase, tuple[str, ...], str | None]
        ] = []

        expected = () if _START_NEGATION.search(normalized) else _matches(
            _EXPECTED_STARTER_RULES, normalized
        )
        pre_match_context = uncertain or bool(expected)
        official_confirmation = official and not pre_match_context
        starter = () if _START_NEGATION.search(normalized) else _matches(
            _STARTER_RULES, normalized
        )
        if expected:
            matches.append((
                TeamSelectionEventKind.EXPECTED_STARTER,
                TeamSelectionEvidencePhase.PRE_MATCH_CLAIM,
                expected,
                None,
            ))
        elif starter:
            matches.append((
                (
                    TeamSelectionEventKind.LINEUP_STARTER
                    if official_confirmation
                    else TeamSelectionEventKind.EXPECTED_STARTER
                ),
                (
                    TeamSelectionEvidencePhase.CONFIRMED_OFFICIAL
                    if official_confirmation
                    else TeamSelectionEvidencePhase.PRE_MATCH_CLAIM
                ),
                starter,
                None,
            ))

        bench = () if _BENCH_NEGATION.search(normalized) else _matches(_BENCH_RULES, normalized)
        self._append(matches, TeamSelectionEventKind.BENCH, bench, official_confirmation)
        self._append(
            matches,
            TeamSelectionEventKind.SQUAD_EXCLUSION,
            _matches(_SQUAD_EXCLUSION_RULES, normalized),
            official_confirmation,
        )
        squad_inclusion = (
            ()
            if _SQUAD_INCLUSION_NEGATION.search(normalized)
            else _matches(_SQUAD_INCLUSION_RULES, normalized)
        )
        self._append(
            matches,
            TeamSelectionEventKind.SQUAD_INCLUSION,
            squad_inclusion,
            official_confirmation,
        )
        self._append(
            matches,
            TeamSelectionEventKind.RESTED_OR_ROTATED,
            _matches(_ROTATION_RULES, normalized),
            official_confirmation,
        )

        positional_role, position_rules = _position_match(normalized)
        if positional_role is not None:
            matches.append((
                TeamSelectionEventKind.POSITIONAL_ROLE_CHANGE,
                _phase(official_confirmation),
                position_rules,
                positional_role,
            ))
        self._append(
            matches,
            TeamSelectionEventKind.CAPTAINCY,
            _matches(_CAPTAINCY_RULES, normalized),
            official_confirmation,
        )
        self._append(
            matches,
            TeamSelectionEventKind.GOALKEEPER_CHANGE,
            _matches(_GOALKEEPER_RULES, normalized),
            official_confirmation,
        )

        signals = tuple(
            self._signal(
                event_kind=event_kind,
                evidence_phase=evidence_phase,
                matched_rules=matched_rules,
                positional_role=positional_role,
                source=source,
                observed_at=observed_at,
                fixture_starts_at=fixture_starts_at,
                uncertain=uncertain,
                aggregate_only=aggregate_only,
            )
            for event_kind, evidence_phase, matched_rules, positional_role in matches
        )
        return TeamSelectionClassification(signals=signals)

    @staticmethod
    def _append(
        matches: list[
            tuple[TeamSelectionEventKind, TeamSelectionEvidencePhase, tuple[str, ...], str | None]
        ],
        event_kind: TeamSelectionEventKind,
        matched_rules: tuple[str, ...],
        official_confirmation: bool,
    ) -> None:
        if matched_rules:
            matches.append((event_kind, _phase(official_confirmation), matched_rules, None))

    @staticmethod
    def _signal(
        *,
        event_kind: TeamSelectionEventKind,
        evidence_phase: TeamSelectionEvidencePhase,
        matched_rules: tuple[str, ...],
        positional_role: str | None,
        source: TwitterSourceAccount,
        observed_at: datetime,
        fixture_starts_at: datetime | None,
        uncertain: bool,
        aggregate_only: bool,
    ) -> TeamSelectionSignal:
        confidence = _BASE_CONFIDENCE[event_kind] * source.trust_weight
        if evidence_phase is TeamSelectionEvidencePhase.PRE_MATCH_CLAIM:
            confidence *= 0.9
        if uncertain:
            confidence *= 0.75
        if aggregate_only:
            confidence = min(confidence, 0.35)
        confidence = round(max(0.0, min(confidence, 1.0)), 4)
        expires_at = _expiry(observed_at, fixture_starts_at, evidence_phase)
        minimum_confidence = (
            0.8
            if evidence_phase is TeamSelectionEvidencePhase.CONFIRMED_OFFICIAL
            else 0.55
        )
        return TeamSelectionSignal(
            event_kind=event_kind,
            evidence_phase=evidence_phase,
            confidence=confidence,
            source_account_kind=source.account_kind,
            source_trust_weight=source.trust_weight,
            observed_at=observed_at,
            expires_at=expires_at,
            actionable=(
                source.enabled
                and not aggregate_only
                and confidence >= minimum_confidence
                and expires_at > observed_at
            ),
            aggregate_only=aggregate_only,
            uncertain=uncertain,
            positional_role=positional_role,
            matched_rules=matched_rules,
        )


def _phase(official_confirmation: bool) -> TeamSelectionEvidencePhase:
    return (
        TeamSelectionEvidencePhase.CONFIRMED_OFFICIAL
        if official_confirmation
        else TeamSelectionEvidencePhase.PRE_MATCH_CLAIM
    )


def _matches(rules: dict[str, str], text: str) -> tuple[str, ...]:
    return tuple(
        name for name, pattern in rules.items() if re.search(pattern, text, re.IGNORECASE)
    )


def _position_match(text: str) -> tuple[str | None, tuple[str, ...]]:
    role_pattern = "|".join(re.escape(role) for role in _ROLES)
    for rule_name, pattern in _POSITION_RULES.items():
        match = re.search(pattern.format(role=f"(?P<role>{role_pattern})"), text, re.IGNORECASE)
        if match:
            return match.group("role").casefold(), (rule_name,)
    return None, ()


def _expiry(
    observed_at: datetime,
    fixture_starts_at: datetime | None,
    evidence_phase: TeamSelectionEvidencePhase,
) -> datetime:
    if fixture_starts_at is not None:
        if evidence_phase is TeamSelectionEvidencePhase.PRE_MATCH_CLAIM:
            return fixture_starts_at
        return fixture_starts_at + timedelta(hours=4)
    return observed_at + (
        timedelta(hours=12)
        if evidence_phase is TeamSelectionEvidencePhase.PRE_MATCH_CLAIM
        else timedelta(hours=8)
    )
