from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ..models import (
    PlayerResolutionStatus,
    TwitterSourceAccount,
)
from ..resolution import PlayerResolver
from .classifier import RuleBasedTeamSelectionClassifier, TeamSelectionClassifier
from .models import (
    TeamResolutionStatus,
    TeamSelectionAssessment,
    TeamSelectionClassification,
)
from .resolution import TeamResolver


class TeamSelectionInterpreter:
    """Combine deterministic signals with safe canonical identity resolution."""

    def __init__(
        self,
        player_resolver: PlayerResolver,
        team_resolver: TeamResolver,
        classifier: TeamSelectionClassifier | None = None,
    ) -> None:
        self._player_resolver = player_resolver
        self._team_resolver = team_resolver
        self._classifier = classifier or RuleBasedTeamSelectionClassifier()

    def assess(
        self,
        text: str,
        source: TwitterSourceAccount,
        observed_at: datetime,
        fixture_starts_at: datetime | None = None,
    ) -> TeamSelectionAssessment:
        source_team_hint = _source_team_hint(source)
        player_resolution = self._player_resolver.resolve(text, source_team_hint)
        team_resolution = self._team_resolver.resolve(text, source_team_hint)
        classification = self._classifier.classify(
            text,
            source,
            observed_at,
            fixture_starts_at,
        )
        identities_resolved = (
            player_resolution.status is PlayerResolutionStatus.RESOLVED
            and team_resolution.status is TeamResolutionStatus.RESOLVED
        )
        return TeamSelectionAssessment(
            player_resolution=player_resolution,
            team_resolution=team_resolution,
            classification=TeamSelectionClassification(
                signals=tuple(
                    replace(signal, actionable=signal.actionable and identities_resolved)
                    for signal in classification.signals
                )
            ),
        )


def _source_team_hint(source: TwitterSourceAccount) -> str | None:
    for key in ("team", "club"):
        value = source.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
