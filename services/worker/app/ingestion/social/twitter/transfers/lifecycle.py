from __future__ import annotations

from datetime import datetime, timedelta

from .models import (
    TeamReference,
    TeamResolutionStatus,
    TransferLifecycle,
    TransferLifecycleDecision,
    TransferMovement,
    TransferSignal,
    TransferStage,
    TransferTerms,
)

_STAGE_RANK = {
    TransferStage.RUMOUR: 1,
    TransferStage.BID: 2,
    TransferStage.NEGOTIATION: 3,
    TransferStage.AGREEMENT: 4,
    TransferStage.MEDICAL: 5,
    TransferStage.CONFIRMED: 6,
}
_EXPIRY_DAYS = {
    TransferStage.RUMOUR: 14,
    TransferStage.BID: 14,
    TransferStage.NEGOTIATION: 21,
    TransferStage.AGREEMENT: 7,
    TransferStage.MEDICAL: 5,
    TransferStage.CONFIRMED: 90,
    TransferStage.DENIED: 14,
    TransferStage.FAILED: 14,
}


class TransferLifecycleStateMachine:
    def decide(
        self,
        *,
        active_lifecycle: TransferLifecycle | None,
        signal: TransferSignal,
        observed_at: datetime,
    ) -> TransferLifecycleDecision:
        if not signal.is_actionable:
            return TransferLifecycleDecision(action="IGNORE", reason=_ignore_reason(signal))

        classification = signal.classification
        assert classification.stage is not None
        assert signal.player_id is not None

        if active_lifecycle is None or active_lifecycle.expires_at <= observed_at:
            return _create_decision(
                signal,
                observed_at,
                reason=(
                    "new_transfer_lifecycle"
                    if active_lifecycle is None
                    else "prior_lifecycle_expired"
                ),
            )

        if active_lifecycle.player_id != signal.player_id:
            return TransferLifecycleDecision(
                action="IGNORE",
                reason="active_lifecycle_player_mismatch",
            )

        if _semantic_conflict(active_lifecycle, signal):
            return TransferLifecycleDecision(
                action="CREATE",
                stage=classification.stage,
                terms=classification.terms,
                movement=classification.movement,
                expires_at=_expires_at(classification.stage, observed_at),
                confidence=classification.confidence,
                player_id=signal.player_id,
                origin_team_id=_resolved_team_id(signal.origin_team),
                destination_team_id=_resolved_team_id(signal.destination_team),
                terminal_at=observed_at if classification.stage.is_terminal else None,
                reason="distinct_transfer_semantics",
            )

        if active_lifecycle.stage.is_terminal:
            if (
                active_lifecycle.stage in {TransferStage.DENIED, TransferStage.FAILED}
                and not classification.stage.is_terminal
                and classification.confidence >= 0.75
            ):
                return _create_decision(
                    signal,
                    observed_at,
                    reason="credible_new_cycle_after_terminal_outcome",
                )
            return TransferLifecycleDecision(
                action="ATTACH",
                stage=active_lifecycle.stage,
                terms=active_lifecycle.terms,
                movement=active_lifecycle.movement,
                expires_at=active_lifecycle.expires_at,
                confidence=max(active_lifecycle.confidence, classification.confidence),
                player_id=active_lifecycle.player_id,
                origin_team_id=active_lifecycle.origin_team_id,
                destination_team_id=active_lifecycle.destination_team_id,
                terminal_at=active_lifecycle.terminal_at,
                reason="terminal_lifecycle_is_immutable",
            )

        next_stage = classification.stage
        if next_stage in {TransferStage.DENIED, TransferStage.FAILED, TransferStage.CONFIRMED}:
            return _update_decision(active_lifecycle, signal, observed_at, next_stage)

        current_rank = _STAGE_RANK[active_lifecycle.stage]
        next_rank = _STAGE_RANK[next_stage]
        if next_rank <= current_rank:
            return TransferLifecycleDecision(
                action="ATTACH",
                stage=active_lifecycle.stage,
                terms=_merge_terms(active_lifecycle.terms, classification.terms),
                movement=_merge_movement(
                    active_lifecycle.movement,
                    classification.movement,
                ),
                expires_at=max(
                    active_lifecycle.expires_at,
                    _expires_at(active_lifecycle.stage, observed_at),
                ),
                confidence=max(active_lifecycle.confidence, classification.confidence),
                player_id=active_lifecycle.player_id,
                origin_team_id=(
                    active_lifecycle.origin_team_id
                    or _resolved_team_id(signal.origin_team)
                ),
                destination_team_id=(
                    active_lifecycle.destination_team_id
                    or _resolved_team_id(signal.destination_team)
                ),
                reason="evidence_does_not_regress_lifecycle",
            )

        return _update_decision(active_lifecycle, signal, observed_at, next_stage)


def _create_decision(
    signal: TransferSignal,
    observed_at: datetime,
    *,
    reason: str,
) -> TransferLifecycleDecision:
    classification = signal.classification
    assert classification.stage is not None
    return TransferLifecycleDecision(
        action="CREATE",
        stage=classification.stage,
        terms=classification.terms,
        movement=classification.movement,
        expires_at=_expires_at(classification.stage, observed_at),
        confidence=classification.confidence,
        player_id=signal.player_id,
        origin_team_id=_resolved_team_id(signal.origin_team),
        destination_team_id=_resolved_team_id(signal.destination_team),
        terminal_at=observed_at if classification.stage.is_terminal else None,
        reason=reason,
    )


def _update_decision(
    active: TransferLifecycle,
    signal: TransferSignal,
    observed_at: datetime,
    stage: TransferStage,
) -> TransferLifecycleDecision:
    classification = signal.classification
    return TransferLifecycleDecision(
        action="UPDATE",
        stage=stage,
        terms=_merge_terms(active.terms, classification.terms),
        movement=_merge_movement(active.movement, classification.movement),
        expires_at=_expires_at(stage, observed_at),
        confidence=max(active.confidence, classification.confidence),
        player_id=active.player_id,
        origin_team_id=active.origin_team_id or _resolved_team_id(signal.origin_team),
        destination_team_id=(
            active.destination_team_id or _resolved_team_id(signal.destination_team)
        ),
        terminal_at=observed_at if stage.is_terminal else None,
        reason="lifecycle_advanced",
    )


def _expires_at(stage: TransferStage, observed_at: datetime) -> datetime:
    return observed_at + timedelta(days=_EXPIRY_DAYS[stage])


def _resolved_team_id(team: TeamReference | None):
    if team is None or team.status is not TeamResolutionStatus.RESOLVED:
        return None
    return team.team_id


def _semantic_conflict(active: TransferLifecycle, signal: TransferSignal) -> bool:
    terms = signal.classification.terms
    movement = signal.classification.movement
    terms_conflict = (
        active.terms is not TransferTerms.UNKNOWN
        and terms is not TransferTerms.UNKNOWN
        and active.terms is not terms
    )
    movement_conflict = (
        active.movement is not TransferMovement.UNKNOWN
        and movement is not TransferMovement.UNKNOWN
        and active.movement is not movement
    )
    destination_id = _resolved_team_id(signal.destination_team)
    destination_conflict = (
        active.destination_team_id is not None
        and destination_id is not None
        and active.destination_team_id != destination_id
    )
    return terms_conflict or movement_conflict or destination_conflict


def _merge_terms(current: TransferTerms, incoming: TransferTerms) -> TransferTerms:
    return incoming if current is TransferTerms.UNKNOWN else current


def _merge_movement(
    current: TransferMovement,
    incoming: TransferMovement,
) -> TransferMovement:
    return incoming if current is TransferMovement.UNKNOWN else current


def _ignore_reason(signal: TransferSignal) -> str:
    classification = signal.classification
    if not classification.has_evidence:
        return "no_transfer_evidence"
    if classification.aggregate_only:
        return "fan_source_is_aggregate_only"
    if classification.negated:
        return "negated_transfer_evidence"
    if classification.confidence < 0.55:
        return "confidence_below_actionable_threshold"
    if signal.player_id is None:
        return "player_not_uniquely_resolved"
    if any(
        team is not None and team.status is TeamResolutionStatus.AMBIGUOUS
        for team in (signal.origin_team, signal.destination_team)
    ):
        return "team_reference_is_ambiguous"
    return "non_actionable_signal"
