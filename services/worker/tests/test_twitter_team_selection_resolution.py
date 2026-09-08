from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID

from app.ingestion.social.twitter import (
    PlayerIdentityCandidate,
    PlayerResolutionStatus,
    PlayerResolver,
    SourceAccountKind,
    TwitterSourceAccount,
)
from app.ingestion.social.twitter.team_selection import (
    TeamIdentityCandidate,
    TeamResolutionStatus,
    TeamResolver,
    TeamSelectionInterpreter,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
PLAYER_ID = UUID("00000000-0000-0000-0000-000000000101")
TEAM_ID = UUID("00000000-0000-0000-0000-000000000201")


class TeamResolverTests(unittest.TestCase):
    def test_exact_alias_resolves_team(self) -> None:
        resolver = TeamResolver([
            TeamIdentityCandidate(TEAM_ID, "Arsenal", ("Arsenal FC", "The Gunners")),
        ])

        result = resolver.resolve("Bukayo Saka starts for Arsenal FC")

        self.assertEqual(result.status, TeamResolutionStatus.RESOLVED)
        self.assertEqual(result.team_id, TEAM_ID)

    def test_same_alias_without_source_hint_is_ambiguous(self) -> None:
        resolver = TeamResolver([
            TeamIdentityCandidate(TEAM_ID, "United", ()),
            TeamIdentityCandidate(
                UUID("00000000-0000-0000-0000-000000000202"),
                "United",
                (),
            ),
        ])

        result = resolver.resolve("Alex Smith starts for United")

        self.assertEqual(result.status, TeamResolutionStatus.AMBIGUOUS)
        self.assertIsNone(result.team_id)

    def test_reviewed_source_hint_can_supply_sparse_team_context(self) -> None:
        resolver = TeamResolver([
            TeamIdentityCandidate(TEAM_ID, "Arsenal", ("Arsenal FC",)),
        ])

        result = resolver.resolve("Bukayo Saka starts.", "Arsenal")

        self.assertEqual(result.status, TeamResolutionStatus.RESOLVED)
        self.assertEqual(result.reason, "reviewed_source_team_hint")


class TeamSelectionInterpreterTests(unittest.TestCase):
    def test_unique_player_and_team_allow_actionable_signal(self) -> None:
        interpreter = _interpreter()

        result = interpreter.assess(
            "Bukayo Saka starts for Arsenal.",
            _source(),
            NOW,
        )

        self.assertEqual(result.player_resolution.status, PlayerResolutionStatus.RESOLVED)
        self.assertEqual(result.team_resolution.status, TeamResolutionStatus.RESOLVED)
        self.assertEqual(len(result.actionable_signals), 1)

    def test_ambiguous_player_blocks_actionable_signals(self) -> None:
        interpreter = TeamSelectionInterpreter(
            PlayerResolver([
                PlayerIdentityCandidate(PLAYER_ID, "Alex Smith", "Arsenal"),
                PlayerIdentityCandidate(
                    UUID("00000000-0000-0000-0000-000000000102"),
                    "Alex Smith",
                    "Arsenal",
                ),
            ]),
            TeamResolver([TeamIdentityCandidate(TEAM_ID, "Arsenal")]),
        )

        result = interpreter.assess(
            "Alex Smith starts for Arsenal.",
            _source(),
            NOW,
        )

        self.assertEqual(result.player_resolution.status, PlayerResolutionStatus.AMBIGUOUS)
        self.assertTrue(result.classification.signals)
        self.assertEqual(result.actionable_signals, ())

    def test_unresolved_team_blocks_actionable_signals(self) -> None:
        interpreter = TeamSelectionInterpreter(
            PlayerResolver([
                PlayerIdentityCandidate(PLAYER_ID, "Bukayo Saka", "Arsenal"),
            ]),
            TeamResolver([]),
        )

        result = interpreter.assess(
            "Bukayo Saka expected to start.",
            _source(metadata={}),
            NOW,
        )

        self.assertEqual(result.team_resolution.status, TeamResolutionStatus.UNRESOLVED)
        self.assertTrue(result.classification.signals)
        self.assertEqual(result.actionable_signals, ())

    def test_disabled_source_is_not_actionable_after_resolution(self) -> None:
        result = _interpreter().assess(
            "Bukayo Saka starts for Arsenal.",
            _source(enabled=False),
            NOW,
        )

        self.assertEqual(result.actionable_signals, ())


def _interpreter() -> TeamSelectionInterpreter:
    return TeamSelectionInterpreter(
        PlayerResolver([
            PlayerIdentityCandidate(PLAYER_ID, "Bukayo Saka", "Arsenal"),
        ]),
        TeamResolver([TeamIdentityCandidate(TEAM_ID, "Arsenal", ("Arsenal FC",))]),
    )


def _source(
    *,
    enabled: bool = True,
    metadata: dict[str, str] | None = None,
) -> TwitterSourceAccount:
    return TwitterSourceAccount(
        id=None,
        twitter_user_id="source-1",
        username="arsenal",
        display_name="Arsenal",
        account_kind=SourceAccountKind.OFFICIAL_CLUB,
        trust_weight=1.0,
        enabled=enabled,
        manually_reviewed_at=NOW,
        reviewed_by="test",
        review_notes="test source",
        metadata={"club": "Arsenal"} if metadata is None else metadata,
    )


if __name__ == "__main__":
    unittest.main()
