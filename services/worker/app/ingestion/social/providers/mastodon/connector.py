from __future__ import annotations

from ...domain import (
    IngestionCursor,
    InvalidSubscription,
    PollResult,
    SocialProvider,
    SocialSubscription,
    SocialSubscriptionMode,
)
from .client import MastodonClient
from .mapper import map_status


class MastodonConnector:
    provider = SocialProvider.MASTODON

    def __init__(self, client: MastodonClient | None = None, *, page_size: int = 40) -> None:
        self._client = client or MastodonClient()
        self._page_size = min(max(page_size, 1), 40)

    async def poll(
        self, subscription: SocialSubscription, cursor: IngestionCursor | None
    ) -> PollResult:
        if subscription.provider is not self.provider or subscription.mode is not SocialSubscriptionMode.AUTHOR_FEED:
            raise InvalidSubscription("Mastodon connector requires an AUTHOR_FEED subscription")
        instance_url = subscription.configuration.get("instance_url")
        account_id = subscription.configuration.get("account_id")
        if not isinstance(instance_url, str) or not isinstance(account_id, str):
            raise InvalidSubscription("Mastodon subscription requires instance_url and account_id")
        since_id = None
        if cursor is not None and cursor.cursor is not None:
            value = cursor.cursor.get("since_id")
            since_id = value if isinstance(value, str) else None
        # Tokens are deliberately not read from subscription JSON. A secret-aware client
        # can be injected for instances that require an application token.
        statuses, rate_limit = await self._client.account_statuses(
            instance_url, account_id, since_id=since_id, limit=self._page_size
        )
        documents = tuple(
            document
            for status in statuses
            if (document := map_status(status, subscription.source_id)) is not None
        )
        newest = max(
            (document.external_id for document in documents),
            key=_id_sort_key,
            default=since_id,
        )
        return PollResult(
            documents=documents,
            next_cursor=None if newest is None else {"since_id": newest},
            rate_limit=rate_limit,
        )


def _id_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (1, int(value))
    except ValueError:
        return (0, value)
