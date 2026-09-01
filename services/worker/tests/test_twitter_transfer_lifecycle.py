from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.ingestion.social.twitter.models import (
    PlayerResolution,
    PlayerResolutionStatus,
    SourceAccountKind,
)
from app.ingestion.social.twitter.transfers import (
    TeamReference,
    TeamResolutionStatus,
    TransferClassification,
    TransferLifecycle,
    TransferLifecycleStateMachine,
    TransferMovement,
    TransferSignal,
    TransferStage,
    TransferTerms,
)


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
PLAYER_ID = UUID("00000000-0000-0000-0000-000000000201")
TEAM_ID = UUID("00000000-0000-0000-0000-000000000301")


class TransferLifecycleStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = TransferLifecycleStateMachine()

    def test_advances_without_requiring_every_stage(self) -> None:
        created = self.machine.decide(
            active_lifecycle=None,
            signal=_signal(TransferStage.RUMOUR, confidence=0.66),
            observed_at=NOW,
        )
        advanced = self.machine.decide(
            active_lifecycle=_lifecycle(TransferStage.RUMOUR),
            signal=_signal(TransferStage.AGREEMENT, confidence=0.91),
            observed_at=NOW + timedelta(days=2),
        )

        self.assertEqual(created.action, "CREATE")
        self.assertEqual(created.expires_at, NOW + timedelta(days=14))
        self.assertEqual(advanced.action, "UPDATE")
        self.assertEqual(advanced.stage, TransferStage.AGREEMENT)
        self.assertEqual(advanced.expires_at, NOW + timedelta(days=9))

    def test_older_evidence_does_not_regress_lifecycle(self) -> None:
        decision = self.machine.decide(
            active_lifecycle=_lifecycle(TransferStage.MEDICAL),
            signal=_signal(TransferStage.NEGOTIATION, confidence=0.82),
            observed_at=NOW + timedelta(days=1),
        )

        self.assertEqual(decision.action, "ATTACH")
        self.assertEqual(decision.stage, TransferStage.MEDICAL)

    def test_denied_and_failed_are_terminal(self) -> None:
        denied = self.machine.decide(
            active_lifecycle=_lifecycle(TransferStage.NEGOTIATION),
            signal=_signal(TransferStage.DENIED, confidence=0.94),
            observed_at=NOW + timedelta(days=1),
        )
        immutable = self.machine.decide(
            active_lifecycle=_lifecycle(TransferStage.FAILED, terminal=True),
            signal=_signal(TransferStage.AGREEMENT, confidence=0.7),
            observed_at=NOW + timedelta(days=1),
        )

        self.assertEqual(denied.action, "UPDATE")
        self.assertEqual(denied.stage, TransferStage.DENIED)
        self.assertEqual(denied.terminal_at, NOW + timedelta(days=1))
        self.assertEqual(immutable.action, "ATTACH")
        self.assertEqual(immutable.stage, TransferStage.FAILED)

    def test_credible_evidence_can_open_new_cycle_after_denial(self) -> None:
        decision = self.machine.decide(
            active_lifecycle=_lifecycle(TransferStage.DENIED, terminal=True),
            signal=_signal(TransferStage.NEGOTIATION, confidence=0.82),
            observed_at=NOW + timedelta(days=1),
        )

        self.assertEqual(decision.action, "CREATE")
        self.assertEqual(decision.reason, "credible_new_cycle_after_terminal_outcome")

    def test_conflicting_destination_starts_distinct_lifecycle(self) -> None:
        other_team = uuid4()
        decision = self.machine.decide(
            active_lifecycle=_lifecycle(
                TransferStage.RUMOUR,
                destination_team_id=TEAM_ID,
            ),
            signal=_signal(
                TransferStage.RUMOUR,
                confidence=0.66,
                destination_team_id=other_team,
            ),
            observed_at=NOW + timedelta(days=1),
        )

        self.assertEqual(decision.action, "CREATE")
        self.assertEqual(decision.destination_team_id, other_team)
        self.assertEqual(decision.reason, "distinct_transfer_semantics")

    def test_expired_lifecycle_is_replaced(self) -> None:
        decision = self.machine.decide(
            active_lifecycle=_lifecycle(
                TransferStage.RUMOUR,
                expires_at=NOW - timedelta(seconds=1),
            ),
            signal=_signal(TransferStage.BID, confidence=0.86),
            observed_at=NOW,
        )

        self.assertEqual(decision.action, "CREATE")
        self.assertEqual(decision.reason, "prior_lifecycle_expired")

    def test_fan_and_ambiguous_signals_are_ignored(self) -> None:
        fan = self.machine.decide(
            active_lifecycle=None,
            signal=_signal(
                TransferStage.CONFIRMED,
                confidence=0.35,
                aggregate_only=True,
                source_kind=SourceAccountKind.FAN,
            ),
            observed_at=NOW,
        )
        ambiguous = self.machine.decide(
            active_lifecycle=None,
            signal=_signal(
                TransferStage.AGREEMENT,
                confidence=0.91,
                destination_status=TeamResolutionStatus.AMBIGUOUS,
            ),
            observed_at=NOW,
        )

        self.assertEqual(fan.action, "IGNORE")
        self.assertEqual(fan.reason, "fan_source_is_aggregate_only")
        self.assertEqual(ambiguous.action, "IGNORE")
        self.assertEqual(ambiguous.reason, "team_reference_is_ambiguous")


def _signal(
    stage: TransferStage,
    *,
    confidence: float,
    aggregate_only: bool = False,
    source_kind: SourceAccountKind = SourceAccountKind.OFFICIAL_CLUB,
    destination_team_id: UUID = TEAM_ID,
    destination_status: TeamResolutionStatus = TeamResolutionStatus.RESOLVED,
) -> TransferSignal:
    destination = TeamReference(
        status=destination_status,
        team_id=destination_team_id if destination_status is TeamResolutionStatus.RESOLVED else None,
        display_name="North FC",
        candidate_team_ids=(
            (destination_team_id,)
            if destination_status is TeamResolutionStatus.RESOLVED
            else (uuid4(), uuid4())
        ),
        reason="test",
    )
    return TransferSignal(
        classification=TransferClassification(
            stage=stage,
            terms=TransferTerms.PERMANENT,
            movement=TransferMovement.ARRIVAL,
            source_kind=source_kind,
            source_trust_weight=1.0,
            base_confidence=confidence,
            confidence=confidence,
            aggregate_only=aggregate_only,
        ),
        player_resolution=PlayerResolution(
            status=PlayerResolutionStatus.RESOLVED,
            player_id=PLAYER_ID,
            candidate_player_ids=(PLAYER_ID,),
            matched_aliases=("Alex Smith",),
            reason="test",
        ),
        destination_team=destination,
    )


def _lifecycle(
    stage: TransferStage,
    *,
    destination_team_id: UUID = TEAM_ID,
    expires_at: datetime | None = None,
    terminal: bool = False,
) -> TransferLifecycle:
    return TransferLifecycle(
        id=uuid4(),
        player_id=PLAYER_ID,
        stage=stage,
        terms=TransferTerms.PERMANENT,
        movement=TransferMovement.ARRIVAL,
        opened_at=NOW - timedelta(days=1),
        last_evidence_at=NOW - timedelta(days=1),
        expires_at=expires_at or NOW + timedelta(days=10),
        confidence=0.8,
        destination_team_id=destination_team_id,
        terminal_at=NOW - timedelta(days=1) if terminal else None,
    )


if __name__ == "__main__":
    unittest.main()
