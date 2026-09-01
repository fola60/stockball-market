from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from app.ingestion.social.twitter import SourceAccountKind, TwitterSourceAccount
from app.ingestion.social.twitter.team_selection import (
    RuleBasedTeamSelectionClassifier,
    TeamSelectionEvidencePhase,
    TeamSelectionEventKind,
)


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
KICKOFF = NOW + timedelta(hours=3)


class RuleBasedTeamSelectionClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = RuleBasedTeamSelectionClassifier()

    def test_official_lineup_can_confirm_starter_captain_and_role(self) -> None:
        result = self.classifier.classify(
            "Arsenal lineup: Bukayo Saka starts at right wing and captains the side.",
            _source(SourceAccountKind.OFFICIAL_CLUB),
            NOW,
            KICKOFF,
        )

        by_kind = {signal.event_kind: signal for signal in result.signals}
        self.assertEqual(
            by_kind[TeamSelectionEventKind.LINEUP_STARTER].evidence_phase,
            TeamSelectionEvidencePhase.CONFIRMED_OFFICIAL,
        )
        self.assertEqual(
            by_kind[TeamSelectionEventKind.POSITIONAL_ROLE_CHANGE].positional_role,
            "right wing",
        )
        self.assertIn(TeamSelectionEventKind.CAPTAINCY, by_kind)
        self.assertTrue(all(signal.actionable for signal in result.signals))
        self.assertTrue(all(signal.expires_at == KICKOFF + timedelta(hours=4) for signal in result.signals))

    def test_journalist_starting_claim_is_not_official_confirmation(self) -> None:
        result = self.classifier.classify(
            "Bukayo Saka starts for Arsenal tonight.",
            _source(SourceAccountKind.CURATED_JOURNALIST, 0.95),
            NOW,
            KICKOFF,
        )

        signal = result.signals[0]
        self.assertEqual(signal.event_kind, TeamSelectionEventKind.EXPECTED_STARTER)
        self.assertEqual(signal.evidence_phase, TeamSelectionEvidencePhase.PRE_MATCH_CLAIM)
        self.assertEqual(signal.source_trust_weight, 0.95)
        self.assertEqual(signal.expires_at, KICKOFF)

    def test_classifies_bench_squad_and_rotation_events(self) -> None:
        cases = {
            "Bukayo Saka is on the bench for Arsenal.": TeamSelectionEventKind.BENCH,
            "Bukayo Saka is named in the Arsenal matchday squad.": (
                TeamSelectionEventKind.SQUAD_INCLUSION
            ),
            "Bukayo Saka is not selected for Arsenal.": TeamSelectionEventKind.SQUAD_EXCLUSION,
            "Bukayo Saka is rested for Arsenal.": TeamSelectionEventKind.RESTED_OR_ROTATED,
        }
        for text, expected in cases.items():
            with self.subTest(expected=expected):
                result = self.classifier.classify(
                    text,
                    _source(SourceAccountKind.OFFICIAL_CLUB),
                    NOW,
                )
                self.assertIn(expected, {signal.event_kind for signal in result.signals})

    def test_classifies_goalkeeper_change(self) -> None:
        result = self.classifier.classify(
            "David Raya replaces Aaron Ramsdale in goal for Arsenal.",
            _source(SourceAccountKind.OFFICIAL_CLUB),
            NOW,
        )

        signal = next(
            signal
            for signal in result.signals
            if signal.event_kind is TeamSelectionEventKind.GOALKEEPER_CHANGE
        )
        self.assertEqual(signal.evidence_phase, TeamSelectionEvidencePhase.CONFIRMED_OFFICIAL)

    def test_fan_signal_is_visible_but_never_actionable(self) -> None:
        result = self.classifier.classify(
            "Bukayo Saka expected to start for Arsenal.",
            _source(SourceAccountKind.FAN, 0.25),
            NOW,
        )

        signal = result.signals[0]
        self.assertTrue(signal.aggregate_only)
        self.assertFalse(signal.actionable)
        self.assertLessEqual(signal.confidence, 0.35)
        self.assertEqual(signal.source_account_kind, SourceAccountKind.FAN)

    def test_uncertainty_reduces_pre_match_confidence(self) -> None:
        certain = self.classifier.classify(
            "Bukayo Saka expected to start for Arsenal.",
            _source(SourceAccountKind.CURATED_JOURNALIST, 0.95),
            NOW,
        ).signals[0]
        uncertain = self.classifier.classify(
            "Bukayo Saka could start for Arsenal.",
            _source(SourceAccountKind.CURATED_JOURNALIST, 0.95),
            NOW,
        ).signals[0]

        self.assertTrue(uncertain.uncertain)
        self.assertLess(uncertain.confidence, certain.confidence)

    def test_negated_start_and_bench_are_not_classified(self) -> None:
        for text in (
            "Bukayo Saka is not expected to start for Arsenal.",
            "Bukayo Saka is not on the bench for Arsenal.",
        ):
            with self.subTest(text=text):
                result = self.classifier.classify(
                    text,
                    _source(SourceAccountKind.OFFICIAL_CLUB),
                    NOW,
                )
                self.assertEqual(result.signals, ())

    def test_negated_squad_inclusion_becomes_exclusion_only(self) -> None:
        result = self.classifier.classify(
            "Bukayo Saka is not named in the Arsenal matchday squad.",
            _source(SourceAccountKind.OFFICIAL_CLUB),
            NOW,
        )

        self.assertEqual(
            {signal.event_kind for signal in result.signals},
            {TeamSelectionEventKind.SQUAD_EXCLUSION},
        )

    def test_pre_match_claim_is_stale_after_known_kickoff(self) -> None:
        result = self.classifier.classify(
            "Bukayo Saka expected to start for Arsenal.",
            _source(SourceAccountKind.CURATED_JOURNALIST, 0.95),
            NOW,
            NOW - timedelta(minutes=1),
        )

        self.assertEqual(result.signals[0].expires_at, NOW - timedelta(minutes=1))
        self.assertFalse(result.signals[0].actionable)


def _source(
    kind: SourceAccountKind,
    trust_weight: float = 1.0,
) -> TwitterSourceAccount:
    return TwitterSourceAccount(
        id=None,
        twitter_user_id="source-1",
        username="source",
        display_name="Source",
        account_kind=kind,
        trust_weight=trust_weight,
        enabled=True,
        manually_reviewed_at=NOW,
        reviewed_by="test",
        review_notes="test source",
        metadata={"club": "Arsenal"},
    )


if __name__ == "__main__":
    unittest.main()
