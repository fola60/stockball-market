from __future__ import annotations

import re

from ..domain import (
    SocialObservationClassification,
    SocialObservationTopic,
    SocialSentiment,
)
from ..twitter.models import InjuryClassification, InjuryEvidenceKind

_POSITIVE_RULES = {
    "achievement": r"\b(?:award|champion|congratulations|milestone|record)\b",
    "availability": r"\b(?:available|back|fit|recovered|returns?|training)\b",
    "praise": r"\b(?:amazing|brilliant|excellent|fantastic|great|impressive|outstanding|superb)\b",
    "production": r"\b(?:assist(?:ed|s)?|clean sheet|goal(?:s|scorer)?|scor(?:e|ed|es|ing))\b",
    "success": r"\b(?:victory|win|wins|won)\b",
}
_NEGATIVE_RULES = {
    "absence": r"\b(?:doubtful|ruled out|side[- ]?lined|suspended|unavailable|will miss)\b",
    "criticism": r"\b(?:awful|disappointing|mistake|poor|struggled|terrible)\b",
    "failure": r"\b(?:defeat|defeated|loss|lost)\b",
    "injury": r"\b(?:injured|injury|knock|surgery)\b",
    "discipline": r"\b(?:red card|sent off)\b",
}
_TOPIC_RULES = {
    SocialObservationTopic.TRANSFER: re.compile(
        r"\b(?:bid|deal|joins?|loan|medical|sign(?:ed|ing)?|transfer|contract)\b",
        re.IGNORECASE,
    ),
    SocialObservationTopic.SELECTION: re.compile(
        r"\b(?:bench|line-?up|named in (?:the )?squad|selected|starting xi|starts?)\b",
        re.IGNORECASE,
    ),
    SocialObservationTopic.PERFORMANCE: re.compile(
        r"\b(?:assist|clean sheet|defeat|goal|performance|player of the match|rating|scored|victory|win)\b",
        re.IGNORECASE,
    ),
}
_COMPILED_POSITIVE = {
    name: re.compile(pattern, re.IGNORECASE) for name, pattern in _POSITIVE_RULES.items()
}
_COMPILED_NEGATIVE = {
    name: re.compile(pattern, re.IGNORECASE) for name, pattern in _NEGATIVE_RULES.items()
}
_RECOVERY_KINDS = {
    InjuryEvidenceKind.RETURN_TO_TRAINING,
    InjuryEvidenceKind.SQUAD_RETURN,
    InjuryEvidenceKind.OFFICIAL_RECOVERY,
    InjuryEvidenceKind.MATCH_PARTICIPATION,
}
_INJURY_KINDS = {
    InjuryEvidenceKind.SUSPECTED_INJURY,
    InjuryEvidenceKind.CONFIRMED_INJURY,
}


class SocialObservationClassifier:
    """Deterministic topic and sentiment baseline for normalized social text."""

    version = "general-rules-v1"

    def classify(
        self,
        text: str,
        injury: InjuryClassification,
    ) -> SocialObservationClassification:
        normalized = " ".join(text.split())
        positive = _matches(_COMPILED_POSITIVE, normalized)
        negative = _matches(_COMPILED_NEGATIVE, normalized)

        topic = _topic(normalized, injury)
        if injury.has_evidence and not injury.negated:
            if injury.evidence_kind in _RECOVERY_KINDS:
                positive.add("injury_recovery")
            elif injury.evidence_kind in _INJURY_KINDS:
                negative.add("injury_evidence")

        if positive and negative:
            sentiment = SocialSentiment.MIXED
        elif positive:
            sentiment = SocialSentiment.POSITIVE
        elif negative:
            sentiment = SocialSentiment.NEGATIVE
        else:
            sentiment = SocialSentiment.NEUTRAL

        total = len(positive) + len(negative)
        score = 0.0 if total == 0 else (len(positive) - len(negative)) / total
        confidence = 0.5 if total == 0 else min(0.95, 0.6 + 0.08 * total)
        if injury.has_evidence and not injury.negated:
            confidence = max(confidence, injury.confidence)
        matched = tuple(sorted((*positive, *negative)))
        return SocialObservationClassification(topic, sentiment, score, confidence, matched)


def _topic(text: str, injury: InjuryClassification) -> SocialObservationTopic:
    if injury.has_evidence and not injury.negated:
        if injury.evidence_kind in _RECOVERY_KINDS:
            return SocialObservationTopic.RECOVERY
        if injury.evidence_kind in _INJURY_KINDS:
            return SocialObservationTopic.INJURY
    for topic in (
        SocialObservationTopic.TRANSFER,
        SocialObservationTopic.SELECTION,
        SocialObservationTopic.PERFORMANCE,
    ):
        if _TOPIC_RULES[topic].search(text):
            return topic
    return SocialObservationTopic.GENERAL


def _matches(patterns: dict[str, re.Pattern[str]], text: str) -> set[str]:
    return {name for name, pattern in patterns.items() if pattern.search(text)}
