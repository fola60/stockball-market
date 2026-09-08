from __future__ import annotations

import re
from typing import Protocol

from .models import (
    InjuryClassification,
    InjuryEvidenceKind,
    TwitterSourceAccount,
)


class InjuryClassifier(Protocol):
    """Boundary for future classifiers; the default implementation is deterministic."""

    def classify(self, text: str, source: TwitterSourceAccount) -> InjuryClassification: ...


_CONFIRMED_INJURY_RULES = {
    "ruled_out": r"\bruled out\b",
    "will_miss": r"\bwill miss\b",
    "diagnosed": r"\bdiagnos(?:ed|is)\b",
    "suffered": r"\bsuffered\b",
    "underwent_surgery": r"\b(?:underwent|had) surgery\b",
    "out_for": r"\bout for (?:at least )?(?:\d+|a|several|few|couple)\b",
    "side_lined": r"\bside[- ]?lined\b",
}
_SUSPECTED_INJURY_RULES = {
    "injury_concern": r"\binjury concern\b",
    "knock": r"\bknock\b",
    "limped_off": r"\blimp(?:ed|ing) off\b",
    "fitness_doubt": r"\bfitness doubt\b",
    "assessment": r"\b(?:being |will be )?assess(?:ed|ment)\b",
    "scan": r"\b(?:awaiting|undergo|undergoing|have) (?:a )?scan\b",
    "could_miss": r"\b(?:could|may|might) miss\b",
    "doubtful": r"\bdoubtful\b",
}
_OFFICIAL_RECOVERY_RULES = {
    "fit_available": r"\bfit and available\b",
    "medically_cleared": r"\bmedically cleared\b",
    "fully_fit": r"\bfully fit\b",
    "cleared_to_play": r"\bcleared to play\b",
}
_SQUAD_RETURN_RULES = {
    "returns_to_squad": r"\breturn(?:s|ed)? to (?:the )?squad\b",
    "named_in_squad": r"\bnamed in (?:the )?squad\b",
    "available_for_selection": r"\bavailable for selection\b",
    "back_in_squad": r"\bback in (?:the )?squad\b",
}
_TRAINING_RETURN_RULES = {
    "returned_training": r"\breturn(?:s|ed)? to (?:full |team )?training\b",
    "back_training": r"\bback in (?:full |team )?training\b",
    "resumed_training": r"\bresumed (?:full |team )?training\b",
}
_MATCH_PARTICIPATION_RULES = {
    "came_on": r"\bcame on (?:in|after|for) (?:the )?\d{1,3}(?:st|nd|rd|th)?\b",
    "played_minutes": r"\bplayed \d{1,3} minutes\b",
    "completed_minutes": r"\bcompleted \d{1,3} minutes\b",
}
_NEGATED_INJURY = re.compile(
    r"\b(?:not injured|no injury|injury (?:has been |was )?ruled out|without injury)\b",
    re.IGNORECASE,
)
_NEGATED_RECOVERY = re.compile(
    r"\b(?:not|hasn'?t|has not|yet to)\s+(?:returned|back|resumed|fit|available|cleared)\b",
    re.IGNORECASE,
)
_UNCERTAINTY = re.compile(
    r"\b(?:reportedly|unconfirmed|rumou?red|possibly|perhaps|appears|seems|could|may|might)\b",
    re.IGNORECASE,
)
_BODY_AREAS = {
    "achilles": r"\bachilles\b",
    "ankle": r"\bankle\b",
    "back": r"\bback\b",
    "calf": r"\bcalf\b",
    "foot": r"\bfoot\b",
    "groin": r"\bgroin\b",
    "hamstring": r"\bhamstring\b",
    "head": r"\bhead\b",
    "hip": r"\bhip\b",
    "knee": r"\bknee\b",
    "shoulder": r"\bshoulder\b",
    "thigh": r"\bthigh\b",
}
_INJURY_TYPES = {
    "concussion": r"\bconcussion\b",
    "fracture": r"\b(?:fracture|fractured|broken)\b",
    "illness": r"\b(?:illness|ill|virus)\b",
    "rupture": r"\b(?:rupture|ruptured)\b",
    "sprain": r"\b(?:sprain|sprained)\b",
    "strain": r"\b(?:strain|strained)\b",
    "tear": r"\b(?:tear|torn)\b",
}
_ABSENCE_RANGE = re.compile(
    r"\b(?:out for|miss(?:es|ing)?|side[- ]?lined for|unavailable for)\s+"
    r"(?:at least\s+)?(\d+)\s*(?:-|to)\s*(\d+)\s*(day|week|month)s?\b",
    re.IGNORECASE,
)
_ABSENCE_SINGLE = re.compile(
    r"\b(?:out for|miss(?:es|ing)?|side[- ]?lined for|unavailable for)\s+"
    r"(?:at least\s+)?(\d+)\s*(day|week|month)s?\b",
    re.IGNORECASE,
)
_ABSENCE_WORDS = re.compile(
    r"\b(?:out for|side[- ]?lined for)\s+(a couple of|a few|several)\s+weeks?\b",
    re.IGNORECASE,
)


class RuleBasedInjuryClassifier:
    """V1 baseline: explicit, deterministic patterns with no model dependency."""

    def classify(self, text: str, source: TwitterSourceAccount) -> InjuryClassification:
        normalized = " ".join(text.split())
        uncertainty = bool(_UNCERTAINTY.search(normalized))
        injury_negated = bool(_NEGATED_INJURY.search(normalized))
        recovery_negated = bool(_NEGATED_RECOVERY.search(normalized))

        matched: list[str] = []
        evidence_kind = InjuryEvidenceKind.NONE
        base_confidence = 0.0

        if not recovery_negated:
            recovery_match = _matches(_OFFICIAL_RECOVERY_RULES, normalized)
            squad_match = _matches(_SQUAD_RETURN_RULES, normalized)
            training_match = _matches(_TRAINING_RETURN_RULES, normalized)
            participation_match = _matches(_MATCH_PARTICIPATION_RULES, normalized)
            if recovery_match:
                evidence_kind = InjuryEvidenceKind.OFFICIAL_RECOVERY
                base_confidence = 0.98
                matched.extend(recovery_match)
            elif participation_match:
                evidence_kind = InjuryEvidenceKind.MATCH_PARTICIPATION
                base_confidence = 0.97
                matched.extend(participation_match)
            elif squad_match:
                evidence_kind = InjuryEvidenceKind.SQUAD_RETURN
                base_confidence = 0.85
                matched.extend(squad_match)
            elif training_match:
                evidence_kind = InjuryEvidenceKind.RETURN_TO_TRAINING
                base_confidence = 0.82
                matched.extend(training_match)

        if evidence_kind is InjuryEvidenceKind.NONE and not injury_negated:
            confirmed_match = _matches(_CONFIRMED_INJURY_RULES, normalized)
            suspected_match = _matches(_SUSPECTED_INJURY_RULES, normalized)
            injury_noun = bool(
                re.search(
                    r"\b(?:injur(?:y|ed)|strain|tear|sprain|fracture|concussion|illness)\b",
                    normalized,
                    re.IGNORECASE,
                )
            )
            if confirmed_match and injury_noun:
                evidence_kind = InjuryEvidenceKind.CONFIRMED_INJURY
                base_confidence = 0.94
                matched.extend(confirmed_match)
            elif suspected_match:
                evidence_kind = InjuryEvidenceKind.SUSPECTED_INJURY
                base_confidence = 0.72
                matched.extend(suspected_match)

        if injury_negated:
            matched.append("negated_injury")
        if recovery_negated:
            matched.append("negated_recovery")
        if uncertainty:
            matched.append("uncertainty")

        confidence = base_confidence * source.trust_weight
        if uncertainty:
            confidence *= 0.7
        aggregate_only = source.account_kind.is_aggregate_only
        if aggregate_only:
            confidence = min(confidence, 0.35)

        absence_min_days, absence_max_days = _extract_absence_window(normalized)
        return InjuryClassification(
            evidence_kind=evidence_kind,
            confidence=round(max(0.0, min(confidence, 1.0)), 4),
            injury_type=_first_match(_INJURY_TYPES, normalized),
            body_area=_first_match(_BODY_AREAS, normalized),
            absence_min_days=absence_min_days,
            absence_max_days=absence_max_days,
            negated=injury_negated or recovery_negated,
            uncertain=uncertainty,
            aggregate_only=aggregate_only,
            matched_rules=tuple(matched),
        )


def _matches(rules: dict[str, str], text: str) -> list[str]:
    return [name for name, pattern in rules.items() if re.search(pattern, text, re.IGNORECASE)]


def _first_match(rules: dict[str, str], text: str) -> str | None:
    for name, pattern in rules.items():
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return None


def _extract_absence_window(text: str) -> tuple[int | None, int | None]:
    range_match = _ABSENCE_RANGE.search(text)
    if range_match:
        factor = _duration_factor(range_match.group(3))
        return int(range_match.group(1)) * factor, int(range_match.group(2)) * factor
    single_match = _ABSENCE_SINGLE.search(text)
    if single_match:
        days = int(single_match.group(1)) * _duration_factor(single_match.group(2))
        return days, days
    words_match = _ABSENCE_WORDS.search(text)
    if words_match:
        return {
            "a couple of": (14, 14),
            "a few": (14, 28),
            "several": (21, 42),
        }[words_match.group(1).casefold()]
    return None, None


def _duration_factor(unit: str) -> int:
    return {"day": 1, "week": 7, "month": 30}[unit.casefold()]

