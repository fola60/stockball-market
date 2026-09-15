from __future__ import annotations

from urllib.parse import urlparse

from ...domain import (
    IngestionCursor,
    InvalidSubscription,
    PollResult,
    SocialProvider,
    SocialSubscription,
    SocialSubscriptionMode,
)
from .client import RssClient
from .parser import parse_feed


class RssConnector:
    provider = SocialProvider.RSS

    def __init__(self, client: RssClient | None = None, *, max_items: int = 100) -> None:
        self._client = client or RssClient()
        self._max_items = max(max_items, 1)

    async def poll(
        self, subscription: SocialSubscription, cursor: IngestionCursor | None
    ) -> PollResult:
        if subscription.provider is not self.provider or subscription.mode is not SocialSubscriptionMode.RSS_FEED:
            raise InvalidSubscription("RSS connector requires an RSS_FEED subscription")
        url = subscription.configuration.get("url")
        if not isinstance(url, str) or not url.strip():
            raise InvalidSubscription("RSS subscription requires an approved URL")
        initial_host = urlparse(url).hostname
        configured_hosts = subscription.configuration.get("approved_redirect_hosts", ())
        if isinstance(configured_hosts, str):
            configured_hosts = (configured_hosts,)
        if not isinstance(configured_hosts, (list, tuple)):
            raise InvalidSubscription("approved_redirect_hosts must be a list")
        allowed_hosts = tuple(
            dict.fromkeys(
                host for host in (initial_host, *(str(value) for value in configured_hosts)) if host
            )
        )
        response = await self._client.fetch(
            url,
            allowed_hosts=allowed_hosts,
            etag=None if cursor is None else cursor.etag,
            last_modified=None if cursor is None else cursor.last_modified,
        )
        next_cursor = dict(cursor.cursor or {}) if cursor is not None else {}
        etag = response.headers.get("etag") or (None if cursor is None else cursor.etag)
        last_modified = response.headers.get("last-modified") or (
            None if cursor is None else cursor.last_modified
        )
        if etag:
            next_cursor["etag"] = etag
        if last_modified:
            next_cursor["last_modified"] = last_modified
        next_cursor["final_url"] = response.final_url
        documents = (
            ()
            if response.status_code == 304
            else parse_feed(
                response.content,
                source_id=subscription.source_id,
                feed_url=response.final_url,
                max_items=self._max_items,
            )
        )
        return PollResult(documents=documents, next_cursor=next_cursor)

