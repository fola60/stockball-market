from __future__ import annotations

from typing import Protocol, Sequence
from uuid import UUID

from ..domain import (
    SocialDocument,
    SocialEntityType,
    SocialObservationClassification,
    SocialObservationStatus,
    SocialSource,
    SocialSourceCategory,
)
from ..injuries.classifier import SocialInjuryClassifier
from ..injuries.processor import InjuryObservationSink, _evidence_status
from ..injuries.resolution import (
    PlayerIdentityCandidate,
    PlayerResolution,
    PlayerResolutionStatus,
)
from .classifier import SocialObservationClassifier
from .resolution import SocialPlayerResolver


class SocialObservationSink(InjuryObservationSink, Protocol):
    def record_social_observation(
        self,
        *,
        document: SocialDocument,
        source: SocialSource,
        resolution: PlayerResolution,
        entity_type: SocialEntityType,
        team_name: str | None,
        classification: SocialObservationClassification,
        classifier_version: str,
        observation_status: SocialObservationStatus,
    ) -> UUID:
        """Upsert a general observation and return its stable database identity."""
        ...


class SocialDocumentProcessor:
    """Create general observations first, then specialized injury evidence when present."""

    def __init__(
        self,
        candidates: Sequence[PlayerIdentityCandidate],
        sink: SocialObservationSink,
        *,
        classifier: SocialObservationClassifier | None = None,
        injury_classifier: SocialInjuryClassifier | None = None,
        editorial_confidence_threshold: float = 0.75,
    ) -> None:
        self._resolver = SocialPlayerResolver(candidates)
        self._sink = sink
        self._classifier = classifier or SocialObservationClassifier()
        self._injury_classifier = injury_classifier or SocialInjuryClassifier()
        self._threshold = editorial_confidence_threshold

    def process(self, document: SocialDocument, source: SocialSource) -> bool:
        club_hint = source.metadata.get("club")
        source_club_hint = club_hint if isinstance(club_hint, str) and club_hint.strip() else None
        source_text_value = document.metadata.get("source_text")
        source_text = (
            source_text_value
            if isinstance(source_text_value, str) and source_text_value.strip()
            else document.text
        )
        social_resolution = self._resolver.resolve(source_text, source_club_hint)
        if social_resolution.player.status is PlayerResolutionStatus.UNRESOLVED:
            enriched_resolution = self._resolver.resolve(document.text, source_club_hint)
            if enriched_resolution.player.status is PlayerResolutionStatus.RESOLVED:
                social_resolution = enriched_resolution
            elif social_resolution.team_name is None:
                social_resolution = enriched_resolution
        resolution = social_resolution.player
        team_name = social_resolution.team_name
        injury_resolution = self._resolver.resolve_strict(source_text, source_club_hint)
        if injury_resolution.status is PlayerResolutionStatus.UNRESOLVED:
            injury_resolution = self._resolver.resolve_strict(
                document.text, source_club_hint
            )
        injury = self._injury_classifier.classify(document.text, source)
        classification = self._classifier.classify(document.text, injury)
        entity_type = _entity_type(resolution, team_name)
        status = _observation_status(source, resolution, entity_type)
        observation_id = self._sink.record_social_observation(
            document=document,
            source=source,
            resolution=resolution,
            entity_type=entity_type,
            team_name=team_name if entity_type is SocialEntityType.TEAM else None,
            classification=classification,
            classifier_version=self._classifier.version,
            observation_status=status,
        )
        if not injury.has_evidence:
            return False
        return self._sink.record_injury_observation(
            document=document,
            source=source,
            resolution=injury_resolution,
            classification=injury,
            classifier_version=self._injury_classifier.version,
            evidence_status=_evidence_status(source, injury, self._threshold),
            social_observation_id=observation_id,
        )


def _entity_type(resolution: PlayerResolution, team_name: str | None) -> SocialEntityType:
    if resolution.player_id is not None:
        return SocialEntityType.PLAYER
    if resolution.status.value == "UNRESOLVED" and team_name is not None:
        return SocialEntityType.TEAM
    return SocialEntityType.UNKNOWN


def _observation_status(
    source: SocialSource,
    resolution: PlayerResolution,
    entity_type: SocialEntityType,
) -> SocialObservationStatus:
    if not source.is_eligible:
        return SocialObservationStatus.REJECTED
    if resolution.status.value == "AMBIGUOUS":
        return SocialObservationStatus.AMBIGUOUS
    if entity_type is SocialEntityType.UNKNOWN:
        return SocialObservationStatus.UNRESOLVED
    if source.source_category is SocialSourceCategory.COMMUNITY:
        return SocialObservationStatus.AGGREGATE_ONLY
    return SocialObservationStatus.INCLUDED
