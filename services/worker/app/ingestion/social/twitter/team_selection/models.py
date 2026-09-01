from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from ..models import PlayerResolution, SourceAccountKind


class TeamSelectionEventKind(StrEnum):
    EXPECTED_STARTER = "EXPECTED_STARTER"
    LINEUP_STARTER = "LINEUP_STARTER"
    BENCH = "BENCH"
    SQUAD_INCLUSION = "SQUAD_INCLUSION"
    SQUAD_EXCLUSION = "SQUAD_EXCLUSION"
    RESTED_OR_ROTATED = "RESTED_OR_ROTATED"
    POSITIONAL_ROLE_CHANGE = "POSITIONAL_ROLE_CHANGE"
    CAPTAINCY = "CAPTAINCY"
    GOALKEEPER_CHANGE = "GOALKEEPER_CHANGE"


class TeamSelectionEvidencePhase(StrEnum):
    PRE_MATCH_CLAIM = "PRE_MATCH_CLAIM"
    CONFIRMED_OFFICIAL = "CONFIRMED_OFFICIAL"


class TeamResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class TeamIdentityCandidate:
    team_id: UUID
    display_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeamResolution:
    status: TeamResolutionStatus
    team_id: UUID | None
    candidate_team_ids: tuple[UUID, ...]
    matched_aliases: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class TeamSelectionSignal:
    event_kind: TeamSelectionEventKind
    evidence_phase: TeamSelectionEvidencePhase
    confidence: float
    source_account_kind: SourceAccountKind
    source_trust_weight: float
    observed_at: datetime
    expires_at: datetime
    actionable: bool
    aggregate_only: bool
    uncertain: bool = False
    positional_role: str | None = None
    matched_rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeamSelectionClassification:
    signals: tuple[TeamSelectionSignal, ...]

    @property
    def actionable_signals(self) -> tuple[TeamSelectionSignal, ...]:
        return tuple(signal for signal in self.signals if signal.actionable)


@dataclass(frozen=True)
class TeamSelectionAssessment:
    player_resolution: PlayerResolution
    team_resolution: TeamResolution
    classification: TeamSelectionClassification

    @property
    def actionable_signals(self) -> tuple[TeamSelectionSignal, ...]:
        return self.classification.actionable_signals
