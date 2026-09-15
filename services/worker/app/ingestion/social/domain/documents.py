from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Mapping, Sequence
from uuid import UUID


class SocialProvider(StrEnum):
    # Kept for compatibility while the previous source-specific tables are backfilled.
    TWITTER = "TWITTER"
    BLUESKY = "BLUESKY"
    RSS = "RSS"
    MASTODON = "MASTODON"


class SocialDocumentKind(StrEnum):
    POST = "POST"
    FEED_ENTRY = "FEED_ENTRY"


@dataclass(frozen=True)
class SocialDocument:
    provider: SocialProvider
    external_id: str
    source_id: UUID
    document_kind: SocialDocumentKind
    author_external_id: str | None
    text: str
    published_at: datetime
    canonical_url: str
    language: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.external_id.strip():
            raise ValueError("social document external_id is required")
        if not self.canonical_url.strip():
            raise ValueError("social document canonical_url is required")
        if self.published_at.tzinfo is None:
            object.__setattr__(self, "published_at", self.published_at.replace(tzinfo=UTC))
        else:
            object.__setattr__(self, "published_at", self.published_at.astimezone(UTC))


@dataclass(frozen=True)
class RateLimitState:
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PollResult:
    documents: Sequence[SocialDocument]
    next_cursor: Mapping[str, object] | None = None
    retry_after: timedelta | None = None
    rate_limit: RateLimitState | None = None
