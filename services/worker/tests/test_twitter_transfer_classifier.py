from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.ingestion.social.twitter.models import (
    PlayerResolution,
    PlayerResolutionStatus,
    SourceAccountKind,
    TwitterSourceAccount,
)
from app.ingestion.social.twitter.transfers import (
    RuleBasedTransferClassifier,
    TeamReference,
    TeamResolutionStatus,
    TransferContext,
    TransferMovement,
    TransferStage,
    TransferTerms,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
PLAYER_ID = UUID("00000000-0000-0000-0000-000000000201")


class RuleBasedTransferClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = RuleBasedTransferClassifier()

    def test_classifies_all_transfer_stages(self) -> None:
        cases = {
            "Arsenal are interested in signing Alex Smith, a transfer target.": (
                TransferStage.RUMOUR
            ),
            "Arsenal made a formal offer for Alex Smith.": TransferStage.BID,
            "Arsenal are in talks to sign Alex Smith.": TransferStage.NEGOTIATION,
            "Deal agreed for Alex Smith to join Arsenal.": TransferStage.AGREEMENT,
            "Alex Smith is set to undergo a medical at Arsenal.": TransferStage.MEDICAL,
            "Alex Smith has signed for Arsenal on a permanent deal.": (
                TransferStage.CONFIRMED
            ),
            "The club denied transfer reports about Alex Smith.": TransferStage.DENIED,
            "The transfer for Alex Smith has collapsed.": TransferStage.FAILED,
        }

        for text, expected in cases.items():
            with self.subTest(expected=expected):
                signal = self.classifier.classify(
                    text,
                    _source(SourceAccountKind.OFFICIAL_CLUB),
                    _context(),
                )
                self.assertEqual(signal.classification.stage, expected)

    def test_extracts_loan_permanent_extension_and_departure_semantics(self) -> None:
        loan = self.classifier.classify(
            "Alex Smith has agreed to join North FC on a season-long loan.",
            _source(SourceAccountKind.CURATED_JOURNALIST, 0.95),
            _context(),
        )
        permanent_departure = self.classifier.classify(
            "Alex Smith will leave South FC in a permanent transfer.",
            _source(SourceAccountKind.CURATED_JOURNALIST, 0.95),
            _context(),
        )
        extension = self.classifier.classify(
            "Alex Smith has signed a new contract with South FC.",
            _source(SourceAccountKind.OFFICIAL_CLUB),
            _context(),
        )

        self.assertEqual(loan.classification.terms, TransferTerms.LOAN)
        self.assertEqual(loan.classification.movement, TransferMovement.ARRIVAL)
        self.assertEqual(permanent_departure.classification.terms, TransferTerms.PERMANENT)
        self.assertEqual(
            permanent_departure.classification.movement,
            TransferMovement.DEPARTURE,
        )
        self.assertEqual(extension.classification.terms, TransferTerms.CONTRACT_EXTENSION)
        self.assertEqual(extension.classification.movement, TransferMovement.RETENTION)

    def test_negated_agreement_does_not_emit_positive_evidence(self) -> None:
        signal = self.classifier.classify(
            "Alex Smith has not agreed a deal with Arsenal.",
            _source(SourceAccountKind.CURATED_JOURNALIST, 0.95),
            _context(),
        )

        self.assertIsNone(signal.classification.stage)
        self.assertTrue(signal.classification.negated)
        self.assertFalse(signal.is_actionable)

    def test_source_weight_is_visible_and_uncertainty_reduces_confidence(self) -> None:
        signal = self.classifier.classify(
            "Alex Smith is reportedly linked with a move to Arsenal.",
            _source(SourceAccountKind.CURATED_JOURNALIST, 0.95),
            _context(),
        )

        self.assertEqual(signal.classification.source_trust_weight, 0.95)
        self.assertEqual(signal.classification.base_confidence, 0.66)
        self.assertEqual(signal.classification.confidence, 0.4703)
        self.assertTrue(signal.classification.uncertain)

    def test_fan_classification_is_aggregate_only_and_not_actionable(self) -> None:
        signal = self.classifier.classify(
            "Alex Smith has signed for Arsenal.",
            _source(SourceAccountKind.FAN, 0.4),
            _context(),
        )

        self.assertTrue(signal.classification.aggregate_only)
        self.assertLessEqual(signal.classification.confidence, 0.35)
        self.assertFalse(signal.is_actionable)

    def test_ambiguous_player_or_team_is_not_actionable(self) -> None:
        ambiguous_player = self.classifier.classify(
            "Deal agreed for Alex Smith to join Arsenal.",
            _source(SourceAccountKind.OFFICIAL_CLUB),
            TransferContext(
                player_resolution=PlayerResolution(
                    status=PlayerResolutionStatus.AMBIGUOUS,
                    player_id=None,
                    candidate_player_ids=(uuid4(), uuid4()),
                    matched_aliases=("Alex Smith",),
                    reason="multiple_exact_alias_matches",
                )
            ),
        )
        ambiguous_team = self.classifier.classify(
            "Deal agreed for Alex Smith to join United.",
            _source(SourceAccountKind.OFFICIAL_CLUB),
            TransferContext(
                player_resolution=_resolved_player(),
                destination_team=TeamReference(
                    status=TeamResolutionStatus.AMBIGUOUS,
                    display_name="United",
                    candidate_team_ids=(uuid4(), uuid4()),
                    reason="multiple_team_matches",
                ),
            ),
        )

        self.assertFalse(ambiguous_player.is_actionable)
        self.assertFalse(ambiguous_team.is_actionable)

    def test_sparse_team_context_does_not_invent_team_reference(self) -> None:
        signal = self.classifier.classify(
            "Alex Smith is in talks over a transfer.",
            _source(SourceAccountKind.OFFICIAL_CLUB),
            _context(),
        )

        self.assertTrue(signal.is_actionable)
        self.assertIsNone(signal.origin_team)
        self.assertIsNone(signal.destination_team)


def _context() -> TransferContext:
    return TransferContext(player_resolution=_resolved_player())


def _resolved_player() -> PlayerResolution:
    return PlayerResolution(
        status=PlayerResolutionStatus.RESOLVED,
        player_id=PLAYER_ID,
        candidate_player_ids=(PLAYER_ID,),
        matched_aliases=("Alex Smith",),
        reason="unique_exact_alias_match",
    )


def _source(
    kind: SourceAccountKind,
    trust_weight: float = 1.0,
) -> TwitterSourceAccount:
    return TwitterSourceAccount(
        id=None,
        twitter_user_id="100",
        username="source",
        display_name="Source",
        account_kind=kind,
        trust_weight=trust_weight,
        enabled=True,
        manually_reviewed_at=NOW,
        reviewed_by="test",
        review_notes="test fixture",
        metadata={},
    )


if __name__ == "__main__":
    unittest.main()
