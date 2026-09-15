from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Mapping
from uuid import UUID

from .documents import SocialProvider


class SocialSourceCategory(StrEnum):
    OFFICIAL_LEAGUE = "OFFICIAL_LEAGUE"
    OFFICIAL_CLUB = "OFFICIAL_CLUB"
    PLAYER = "PLAYER"
    JOURNALIST = "JOURNALIST"
    NEWS_ORGANISATION = "NEWS_ORGANISATION"
    COMMUNITY = "COMMUNITY"

    @property
    def can_update_episodes(self) -> bool:
        return self is not self.COMMUNITY

    @property
    def is_official(self) -> bool:
        return self in {self.OFFICIAL_LEAGUE, self.OFFICIAL_CLUB}


class SocialPolicyStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SocialSubscriptionMode(StrEnum):
    AUTHOR_FEED = "AUTHOR_FEED"
    RSS_FEED = "RSS_FEED"
    STREAM = "STREAM"


@dataclass(frozen=True)
class SocialSource:
    id: UUID
    provider: SocialProvider
    external_source_id: str
    display_handle: str | None
    canonical_url: str
    source_category: SocialSourceCategory
    trust_weight: float
    enabled: bool
    policy_status: SocialPolicyStatus
    terms_reviewed_at: datetime
    retention_days: int
    approved_by: str
    approved_at: datetime
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.external_source_id.strip():
            raise ValueError("social source external_source_id is required")
        if not 0 <= self.trust_weight <= 1:
            raise ValueError("social source trust_weight must be between 0 and 1")
        if self.retention_days < 0:
            raise ValueError("social source retention_days cannot be negative")
        if self.enabled and self.policy_status is not SocialPolicyStatus.APPROVED:
            raise ValueError("only approved social sources can be enabled")

    @property
    def is_eligible(self) -> bool:
        return self.enabled and self.policy_status is SocialPolicyStatus.APPROVED


@dataclass(frozen=True)
class SocialSubscription:
    id: UUID
    source_id: UUID
    provider: SocialProvider
    mode: SocialSubscriptionMode
    configuration: Mapping[str, object]
    polling_interval: timedelta
    enabled: bool = True
    next_eligible_poll_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.polling_interval <= timedelta():
            raise ValueError("social subscription polling_interval must be positive")
