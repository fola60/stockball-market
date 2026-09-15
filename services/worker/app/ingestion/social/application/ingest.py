from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import UUID

from ..domain import (
    InvalidSubscription,
    PermanentProviderError,
    PolicyDisabled,
    RateLimited,
    SocialProvider,
    TransientProviderError,
)
from ..ports import SocialRepository
from .source_registry import SourceRegistry


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class SocialIngestionResult:
    subscription_id: UUID
    provider: SocialProvider
    fetched_documents: int
    inserted_documents: int
    duplicate_documents: int
    next_eligible_poll_at: datetime


class SocialIngestionService:
    def __init__(
        self,
        repository: SocialRepository,
        registry: SourceRegistry,
        *,
        clock: Callable[[], datetime] = _utc_now,
        random_value: Callable[[], float] = random.random,
        max_backoff: timedelta = timedelta(hours=6),
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._clock = clock
        self._random_value = random_value
        self._max_backoff = max_backoff

    async def ingest(self, subscription_id: UUID) -> SocialIngestionResult:
        subscription = self._repository.get_subscription(subscription_id)
        if subscription is None:
            raise InvalidSubscription(f"social subscription {subscription_id} does not exist")
        source = self._repository.get_source(subscription.source_id)
        if source is None:
            raise InvalidSubscription(f"social source {subscription.source_id} does not exist")
        connector = self._registry.connector_for(subscription, source)
        cursor = self._repository.load_cursor(subscription.id)
        now = self._clock()
        eligible_at = (
            cursor.next_eligible_poll_at
            if cursor is not None and cursor.next_eligible_poll_at is not None
            else subscription.next_eligible_poll_at
        )
        if eligible_at is not None and eligible_at > now:
            raise RateLimited("social subscription is still in backoff", retry_at=eligible_at)

        try:
            result = await connector.poll(subscription, cursor)
        except RateLimited as error:
            retry_at = self._retry_at(error, now, cursor.consecutive_failures if cursor else 0)
            self._repository.record_failure(subscription.id, now, retry_at, "RateLimited")
            raise
        except TransientProviderError:
            retry_at = self._backoff_at(now, cursor.consecutive_failures if cursor else 0)
            self._repository.record_failure(
                subscription.id, now, retry_at, "TransientProviderError"
            )
            raise
        except (InvalidSubscription, PolicyDisabled, PermanentProviderError) as error:
            self._repository.record_failure(
                subscription.id,
                now,
                now + self._max_backoff,
                type(error).__name__,
            )
            raise

        inserted, duplicates = self._repository.persist_poll_result(
            subscription, result, now
        )
        next_eligible = now + (result.retry_after or subscription.polling_interval)
        return SocialIngestionResult(
            subscription_id=subscription.id,
            provider=subscription.provider,
            fetched_documents=len(result.documents),
            inserted_documents=inserted,
            duplicate_documents=duplicates,
            next_eligible_poll_at=next_eligible,
        )

    def _retry_at(self, error: RateLimited, now: datetime, failures: int) -> datetime:
        if error.retry_at is not None:
            return error.retry_at
        if error.retry_after is not None:
            return now + error.retry_after
        return self._backoff_at(now, failures)

    def _backoff_at(self, now: datetime, failures: int) -> datetime:
        seconds = min(30 * (2 ** min(failures, 10)), self._max_backoff.total_seconds())
        jitter = seconds * 0.2 * self._random_value()
        return now + timedelta(seconds=seconds + jitter)

