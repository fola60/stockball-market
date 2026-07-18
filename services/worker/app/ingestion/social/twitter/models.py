from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID


class InjuryStage(StrEnum):
    SUSPECTED_INJURY = "SUSPECTED_INJURY"
    CONFIRMED_INJURY = "CONFIRMED_INJURY"
    SUSPECTED_RECOVERY = "SUSPECTED_RECOVERY"
    CONFIRMED_RECOVERED = "CONFIRMED_RECOVERED"


class SourceAccountKind(StrEnum):
    OFFICIAL_CLUB = "OFFICIAL_CLUB"
    OFFICIAL_LEAGUE = "OFFICIAL_LEAGUE"
    PLAYER_OWNED = "PLAYER_OWNED"
    CURATED_JOURNALIST = "CURATED_JOURNALIST"
    FAN = "FAN"

    @property
    def is_official(self) -> bool:
        return self in {self.OFFICIAL_CLUB, self.OFFICIAL_LEAGUE}

    @property
    def is_aggregate_only(self) -> bool:
        return self is self.FAN


class PlayerResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


class InjuryEvidenceKind(StrEnum):
    NONE = "NONE"
    SUSPECTED_INJURY = "SUSPECTED_INJURY"
    CONFIRMED_INJURY = "CONFIRMED_INJURY"
    RETURN_TO_TRAINING = "RETURN_TO_TRAINING"
    SQUAD_RETURN = "SQUAD_RETURN"
    OFFICIAL_RECOVERY = "OFFICIAL_RECOVERY"
    MATCH_PARTICIPATION = "MATCH_PARTICIPATION"


@dataclass(frozen=True)
class TwitterSourceAccount:
    id: UUID | None
    twitter_user_id: str
    username: str
    display_name: str
    account_kind: SourceAccountKind
    trust_weight: float
    enabled: bool
    manually_reviewed_at: datetime
    reviewed_by: str
    review_notes: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class PlayerAlias:
    alias: str
    alias_type: str
    club_hint: str | None = None


@dataclass(frozen=True)
class PlayerIdentityCandidate:
    player_id: UUID
    display_name: str
    club: str | None
    aliases: tuple[PlayerAlias, ...] = ()


@dataclass(frozen=True)
class PlayerResolution:
    status: PlayerResolutionStatus
    player_id: UUID | None
    candidate_player_ids: tuple[UUID, ...]
    matched_aliases: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class TwitterPost:
    post_id: str
    author_id: str
    text: str
    created_at: datetime
    lang: str | None
    conversation_id: str | None
    referenced_post_ids: tuple[str, ...]
    edit_history_post_ids: tuple[str, ...]

    @property
    def terms_compatible_metadata(self) -> Mapping[str, Any]:
        # Text and profile metrics intentionally remain transient.
        return {
            "conversation_id": self.conversation_id,
            "referenced_post_ids": list(self.referenced_post_ids),
            "edit_history_post_ids": list(self.edit_history_post_ids),
        }


@dataclass(frozen=True)
class TwitterRateLimit:
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None


@dataclass(frozen=True)
class TwitterSearchPage:
    posts: tuple[TwitterPost, ...]
    newest_id: str | None
    next_token: str | None
    rate_limit: TwitterRateLimit


@dataclass(frozen=True)
class TwitterIngestionCursor:
    query_key: str
    query: str
    since_id: str | None = None
    next_token: str | None = None
    pending_newest_id: str | None = None
    rate_limit: TwitterRateLimit = TwitterRateLimit()


@dataclass(frozen=True)
class InjuryClassification:
    evidence_kind: InjuryEvidenceKind
    confidence: float
    injury_type: str | None = None
    body_area: str | None = None
    absence_min_days: int | None = None
    absence_max_days: int | None = None
    negated: bool = False
    uncertain: bool = False
    aggregate_only: bool = False
    matched_rules: tuple[str, ...] = ()

    @property
    def has_evidence(self) -> bool:
        return self.evidence_kind is not InjuryEvidenceKind.NONE


@dataclass(frozen=True)
class InjuryEpisode:
    id: UUID
    player_id: UUID
    stage: InjuryStage
    started_at: datetime
    last_evidence_at: datetime
    expected_absence_until: datetime | None
    expires_at: datetime
    confidence: float
    injury_type: str | None = None
    body_area: str | None = None
    recurrence_of_episode_id: UUID | None = None
    recovered_at: datetime | None = None
    expired_at: datetime | None = None


@dataclass(frozen=True)
class EpisodeDecision:
    action: str
    stage: InjuryStage | None = None
    expected_absence_until: datetime | None = None
    expires_at: datetime | None = None
    confidence: float = 0.0
    injury_type: str | None = None
    body_area: str | None = None
    recurrence_of_episode_id: UUID | None = None
    reason: str = ""


@dataclass(frozen=True)
class MatchParticipationEvidence:
    player_id: UUID
    fixture_id: UUID
    observed_at: datetime
    minutes: float
    provider: str


@dataclass(frozen=True)
class PlayerInjuryAvailabilityObservation:
    player_id: UUID
    injury_episode_id: UUID
    stage: InjuryStage
    confidence: float
    observed_at: datetime
    expected_absence_until: datetime | None
    injury_type: str | None
    body_area: str | None
    evidence_kind: InjuryEvidenceKind
    source_account_kind: SourceAccountKind | None
    is_available: bool


@dataclass(frozen=True)
class TwitterInjuryIngestionResult:
    fetched_posts: int
    persisted_posts: int
    classified_posts: int
    resolved_posts: int
    ambiguous_posts: int
    episode_updates: int
    skipped_posts: int
    pages_fetched: int
    participation_recoveries: int = 0


@dataclass(frozen=True)
class PendingPostObservation:
    observation_id: UUID
    already_processed: bool
    episode_id: UUID | None = None
    was_created: bool = False
