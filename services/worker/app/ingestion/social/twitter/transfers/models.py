from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from ..models import (
    PlayerResolution,
    PlayerResolutionStatus,
    SourceAccountKind,
)


class TransferStage(StrEnum):
    RUMOUR = "RUMOUR"
    BID = "BID"
    NEGOTIATION = "NEGOTIATION"
    AGREEMENT = "AGREEMENT"
    MEDICAL = "MEDICAL"
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        return self in {self.CONFIRMED, self.DENIED, self.FAILED}


class TransferTerms(StrEnum):
    UNKNOWN = "UNKNOWN"
    PERMANENT = "PERMANENT"
    LOAN = "LOAN"
    CONTRACT_EXTENSION = "CONTRACT_EXTENSION"


class TransferMovement(StrEnum):
    UNKNOWN = "UNKNOWN"
    ARRIVAL = "ARRIVAL"
    DEPARTURE = "DEPARTURE"
    RETENTION = "RETENTION"


class TeamResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class TeamReference:
    status: TeamResolutionStatus
    team_id: UUID | None = None
    display_name: str | None = None
    candidate_team_ids: tuple[UUID, ...] = ()
    reason: str = ""

    @classmethod
    def resolved(cls, team_id: UUID, display_name: str) -> TeamReference:
        return cls(
            status=TeamResolutionStatus.RESOLVED,
            team_id=team_id,
            display_name=display_name,
            candidate_team_ids=(team_id,),
            reason="caller_resolved_canonical_team",
        )


@dataclass(frozen=True)
class TransferContext:
    player_resolution: PlayerResolution
    origin_team: TeamReference | None = None
    destination_team: TeamReference | None = None


@dataclass(frozen=True)
class TransferClassification:
    stage: TransferStage | None
    terms: TransferTerms
    movement: TransferMovement
    source_kind: SourceAccountKind
    source_trust_weight: float
    base_confidence: float
    confidence: float
    aggregate_only: bool
    negated: bool = False
    uncertain: bool = False
    matched_rules: tuple[str, ...] = ()

    @property
    def has_evidence(self) -> bool:
        return self.stage is not None


@dataclass(frozen=True)
class TransferSignal:
    classification: TransferClassification
    player_resolution: PlayerResolution
    origin_team: TeamReference | None = None
    destination_team: TeamReference | None = None

    @property
    def player_id(self) -> UUID | None:
        return self.player_resolution.player_id

    @property
    def is_actionable(self) -> bool:
        classification = self.classification
        if (
            not classification.has_evidence
            or classification.aggregate_only
            or classification.negated
            or classification.confidence < 0.55
        ):
            return False
        if (
            self.player_resolution.status is not PlayerResolutionStatus.RESOLVED
            or self.player_resolution.player_id is None
        ):
            return False
        return not any(
            team is not None and team.status is TeamResolutionStatus.AMBIGUOUS
            for team in (self.origin_team, self.destination_team)
        )


@dataclass(frozen=True)
class TransferLifecycle:
    id: UUID
    player_id: UUID
    stage: TransferStage
    terms: TransferTerms
    movement: TransferMovement
    opened_at: datetime
    last_evidence_at: datetime
    expires_at: datetime
    confidence: float
    origin_team_id: UUID | None = None
    destination_team_id: UUID | None = None
    terminal_at: datetime | None = None


@dataclass(frozen=True)
class TransferLifecycleDecision:
    action: str
    stage: TransferStage | None = None
    terms: TransferTerms = TransferTerms.UNKNOWN
    movement: TransferMovement = TransferMovement.UNKNOWN
    expires_at: datetime | None = None
    confidence: float = 0.0
    player_id: UUID | None = None
    origin_team_id: UUID | None = None
    destination_team_id: UUID | None = None
    terminal_at: datetime | None = None
    reason: str = ""
