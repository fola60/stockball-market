from __future__ import annotations

from typing import Protocol

from ..domain import IngestionCursor, PollResult, SocialProvider, SocialSubscription


class SocialConnector(Protocol):
    provider: SocialProvider

    async def poll(
        self,
        subscription: SocialSubscription,
        cursor: IngestionCursor | None,
    ) -> PollResult: ...

