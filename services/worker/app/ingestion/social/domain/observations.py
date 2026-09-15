from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SocialObservationTopic(StrEnum):
    GENERAL = "GENERAL"
    PERFORMANCE = "PERFORMANCE"
    SELECTION = "SELECTION"
    TRANSFER = "TRANSFER"
    INJURY = "INJURY"
    RECOVERY = "RECOVERY"


class SocialSentiment(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


class SocialObservationStatus(StrEnum):
    INCLUDED = "INCLUDED"
    AGGREGATE_ONLY = "AGGREGATE_ONLY"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class SocialEntityType(StrEnum):
    PLAYER = "PLAYER"
    TEAM = "TEAM"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SocialObservationClassification:
    topic: SocialObservationTopic
    sentiment: SocialSentiment
    sentiment_score: float
    confidence: float
    matched_rules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not -1 <= self.sentiment_score <= 1:
            raise ValueError("social sentiment score must be between -1 and 1")
        if not 0 <= self.confidence <= 1:
            raise ValueError("social observation confidence must be between 0 and 1")
