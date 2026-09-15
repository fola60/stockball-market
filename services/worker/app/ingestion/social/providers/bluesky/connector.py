from __future__ import annotations

from collections.abc import Mapping

from ...domain import (
    IngestionCursor,
    InvalidSubscription,
    PollResult,
    SocialProvider,
    SocialSubscription,
    SocialSubscriptionMode,
)
from .client import BlueskyClient
from .mapper import map_feed_item


class BlueskyConnector:
    provider = SocialProvider.BLUESKY

    def __init__(self, client: BlueskyClient | None = None, *, page_size: int = 100) -> None:
        self._client = client or BlueskyClient()
        self._page_size = min(max(page_size, 1), 100)

    async def poll(
        self, subscription: SocialSubscription, cursor: IngestionCursor | None
    ) -> PollResult:
        if subscription.provider is not self.provider or subscription.mode is not SocialSubscriptionMode.AUTHOR_FEED:
            raise InvalidSubscription("Bluesky connector requires an AUTHOR_FEED subscription")
        actor = subscription.configuration.get("did")
        if not isinstance(actor, str) or not actor.startswith("did:"):
            raise InvalidSubscription("Bluesky subscription requires a reviewed DID")
        provider_cursor = None
        if cursor is not None and isinstance(cursor.cursor, Mapping):
            value = cursor.cursor.get("cursor")
            provider_cursor = value if isinstance(value, str) else None
        payload, rate_limit = await self._client.get_author_feed(
            actor, cursor=provider_cursor, limit=self._page_size
        )
        raw_feed = payload.get("feed", [])
        if not isinstance(raw_feed, list):
            raise InvalidSubscription("Bluesky author feed response has no feed list")
        documents = tuple(
            document
            for item in raw_feed
            if isinstance(item, Mapping)
            if (document := map_feed_item(item, subscription.source_id)) is not None
        )
        next_value = payload.get("cursor")
        next_cursor = {"cursor": next_value} if isinstance(next_value, str) else None
        return PollResult(documents=documents, next_cursor=next_cursor, rate_limit=rate_limit)

