from __future__ import annotations

from typing import Protocol, Sequence
from uuid import UUID

from ..domain import SocialDocument, SocialSource, SocialSourceCategory
from ..twitter.models import (
    InjuryClassification,
    PlayerIdentityCandidate,
    PlayerResolution,
)
from .classifier import SocialInjuryClassifier
from .resolution import PlayerResolver


class InjuryObservationSink(Protocol):
    def record_injury_observation(
        self,
        *,
        document: SocialDocument,
        source: SocialSource,
        resolution: PlayerResolution,
        classification: InjuryClassification,
        classifier_version: str,
        evidence_status: str,
        social_observation_id: UUID | None = None,
    ) -> bool:
        """Idempotently store the observation and apply any episode transition."""
        ...


class InjuryDocumentProcessor:
    def __init__(
        self,
        candidates: Sequence[PlayerIdentityCandidate],
        sink: InjuryObservationSink,
        *,
        classifier: SocialInjuryClassifier | None = None,
        editorial_confidence_threshold: float = 0.75,
    ) -> None:
        self._resolver = PlayerResolver(candidates)
        self._sink = sink
        self._classifier = classifier or SocialInjuryClassifier()
        self._threshold = editorial_confidence_threshold

    def process(self, document: SocialDocument, source: SocialSource) -> bool:
        club_hint = source.metadata.get("club")
        resolution = self._resolver.resolve(
            document.text, club_hint if isinstance(club_hint, str) else None
        )
        classification = self._classifier.classify(document.text, source)
        status = _evidence_status(source, classification, self._threshold)
        return self._sink.record_injury_observation(
            document=document,
            source=source,
            resolution=resolution,
            classification=classification,
            classifier_version=self._classifier.version,
            evidence_status=status,
            social_observation_id=None,
        )


def _evidence_status(
    source: SocialSource,
    classification: InjuryClassification,
    editorial_confidence_threshold: float,
) -> str:
    if not source.is_eligible:
        return "REJECTED"
    if not classification.has_evidence or classification.negated:
        return "REJECTED"
    if source.source_category is SocialSourceCategory.COMMUNITY:
        return "AGGREGATE_ONLY"
    if source.source_category in {
        SocialSourceCategory.JOURNALIST,
        SocialSourceCategory.NEWS_ORGANISATION,
    } and classification.confidence < editorial_confidence_threshold:
        return "PENDING"
    return "ACTIONABLE"
