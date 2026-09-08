from __future__ import annotations

from datetime import datetime, timedelta

from .models import (
    EpisodeDecision,
    InjuryClassification,
    InjuryEpisode,
    InjuryEvidenceKind,
    InjuryStage,
    SourceAccountKind,
)

SUSPECTED_EXPIRY_DAYS = 14
CONFIRMED_DEFAULT_EXPIRY_DAYS = 180
EXPECTED_RETURN_GRACE_DAYS = 14
RECOVERY_EXPIRY_DAYS = 30


class InjuryEpisodeStateMachine:
    def decide(
        self,
        *,
        active_episode: InjuryEpisode | None,
        latest_recovered_episode: InjuryEpisode | None,
        classification: InjuryClassification,
        source_kind: SourceAccountKind | None,
        observed_at: datetime,
    ) -> EpisodeDecision:
        if (
            not classification.has_evidence
            or classification.negated
            or classification.aggregate_only
        ):
            return EpisodeDecision(action="IGNORE", reason="non_actionable_evidence")

        expected_until = _expected_absence_until(classification, observed_at)
        if classification.evidence_kind in {
            InjuryEvidenceKind.SUSPECTED_INJURY,
            InjuryEvidenceKind.CONFIRMED_INJURY,
        }:
            return self._injury_decision(
                active_episode=active_episode,
                latest_recovered_episode=latest_recovered_episode,
                classification=classification,
                observed_at=observed_at,
                expected_until=expected_until,
            )

        if active_episode is None:
            return EpisodeDecision(action="IGNORE", reason="recovery_without_active_episode")

        if (
            classification.evidence_kind is InjuryEvidenceKind.MATCH_PARTICIPATION
            and classification.confidence >= 0.9
        ):
            return _recovered_decision(
                active_episode, classification, observed_at, "strong_match_participation"
            )
        if (
            classification.evidence_kind is InjuryEvidenceKind.OFFICIAL_RECOVERY
            and source_kind is not None
            and source_kind.is_official
            and classification.confidence >= 0.9
        ):
            return _recovered_decision(
                active_episode, classification, observed_at, "high_confidence_official_recovery"
            )
        if (
            classification.evidence_kind
            in {
                InjuryEvidenceKind.RETURN_TO_TRAINING,
                InjuryEvidenceKind.SQUAD_RETURN,
                InjuryEvidenceKind.OFFICIAL_RECOVERY,
            }
            and classification.confidence >= 0.65
        ):
            return EpisodeDecision(
                action="UPDATE",
                stage=InjuryStage.SUSPECTED_RECOVERY,
                expected_absence_until=active_episode.expected_absence_until,
                expires_at=observed_at + timedelta(days=RECOVERY_EXPIRY_DAYS),
                confidence=max(active_episode.confidence, classification.confidence),
                injury_type=active_episode.injury_type,
                body_area=active_episode.body_area,
                reason="training_or_squad_return",
            )
        return EpisodeDecision(action="ATTACH", reason="weak_recovery_update")

    def _injury_decision(
        self,
        *,
        active_episode: InjuryEpisode | None,
        latest_recovered_episode: InjuryEpisode | None,
        classification: InjuryClassification,
        observed_at: datetime,
        expected_until: datetime | None,
    ) -> EpisodeDecision:
        confirmed = (
            classification.evidence_kind is InjuryEvidenceKind.CONFIRMED_INJURY
            and classification.confidence >= 0.75
        )
        stage = InjuryStage.CONFIRMED_INJURY if confirmed else InjuryStage.SUSPECTED_INJURY
        if active_episode is None:
            expiry = _expiry_for(stage, observed_at, expected_until)
            return EpisodeDecision(
                action="CREATE",
                stage=stage,
                expected_absence_until=expected_until,
                expires_at=expiry,
                confidence=classification.confidence,
                injury_type=classification.injury_type,
                body_area=classification.body_area,
                recurrence_of_episode_id=(
                    None if latest_recovered_episode is None else latest_recovered_episode.id
                ),
                reason=(
                    "recurrence_after_recovery"
                    if latest_recovered_episode is not None
                    else "new_injury_episode"
                ),
            )

        next_stage = active_episode.stage
        if confirmed or active_episode.stage is InjuryStage.SUSPECTED_RECOVERY:
            next_stage = InjuryStage.CONFIRMED_INJURY
        merged_expected_until = _later(
            active_episode.expected_absence_until,
            expected_until,
        )
        return EpisodeDecision(
            action="UPDATE",
            stage=next_stage,
            expected_absence_until=merged_expected_until,
            expires_at=_expiry_for(next_stage, observed_at, merged_expected_until),
            confidence=max(active_episode.confidence, classification.confidence),
            injury_type=classification.injury_type or active_episode.injury_type,
            body_area=classification.body_area or active_episode.body_area,
            reason=(
                "injury_setback_during_recovery"
                if active_episode.stage is InjuryStage.SUSPECTED_RECOVERY
                else "active_episode_update"
            ),
        )


def _recovered_decision(
    active_episode: InjuryEpisode,
    classification: InjuryClassification,
    observed_at: datetime,
    reason: str,
) -> EpisodeDecision:
    return EpisodeDecision(
        action="UPDATE",
        stage=InjuryStage.CONFIRMED_RECOVERED,
        expected_absence_until=active_episode.expected_absence_until,
        expires_at=observed_at,
        confidence=max(active_episode.confidence, classification.confidence),
        injury_type=active_episode.injury_type,
        body_area=active_episode.body_area,
        reason=reason,
    )


def _expected_absence_until(
    classification: InjuryClassification,
    observed_at: datetime,
) -> datetime | None:
    if classification.absence_max_days is None:
        return None
    return observed_at + timedelta(days=classification.absence_max_days)


def _expiry_for(
    stage: InjuryStage,
    observed_at: datetime,
    expected_until: datetime | None,
) -> datetime:
    if stage is InjuryStage.SUSPECTED_INJURY:
        fallback = observed_at + timedelta(days=SUSPECTED_EXPIRY_DAYS)
    else:
        fallback = observed_at + timedelta(days=CONFIRMED_DEFAULT_EXPIRY_DAYS)
    if expected_until is None:
        return fallback
    return max(
        observed_at + timedelta(days=SUSPECTED_EXPIRY_DAYS),
        expected_until + timedelta(days=EXPECTED_RETURN_GRACE_DAYS),
    )


def _later(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)
