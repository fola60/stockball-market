from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from uuid import UUID

from .documents import RateLimitState


@dataclass(frozen=True)
class IngestionCursor:
    subscription_id: UUID
    cursor: Mapping[str, object] | None = None
    etag: str | None = None
    last_modified: str | None = None
    last_polled_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    next_eligible_poll_at: datetime | None = None
    rate_limit: RateLimitState | None = None

