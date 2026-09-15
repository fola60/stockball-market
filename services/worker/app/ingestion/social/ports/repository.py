from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from ..domain import (
    IngestionCursor,
    PollResult,
    SocialSource,
    SocialSubscription,
)


class SocialRepository(Protocol):
    def upsert_source(self, source: SocialSource) -> UUID: ...

    def upsert_subscription(self, subscription: SocialSubscription) -> UUID: ...

    def get_source(self, source_id: UUID) -> SocialSource | None: ...

    def get_subscription(self, subscription_id: UUID) -> SocialSubscription | None: ...

    def list_due_subscriptions(
        self,
        as_of: datetime,
        *,
        limit: int = 100,
        provider: str | None = None,
    ) -> list[UUID]: ...

    def load_cursor(self, subscription_id: UUID) -> IngestionCursor | None: ...

    def persist_poll_result(
        self,
        subscription: SocialSubscription,
        result: PollResult,
        polled_at: datetime,
    ) -> tuple[int, int]:
        """Atomically store documents, queue new ones, and advance the cursor.

        Returns ``(inserted, duplicates)``.
        """
        ...

    def record_failure(
        self,
        subscription_id: UUID,
        failed_at: datetime,
        next_eligible_poll_at: datetime,
        error_type: str,
    ) -> None: ...
