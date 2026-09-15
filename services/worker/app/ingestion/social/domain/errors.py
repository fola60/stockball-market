from __future__ import annotations

from datetime import datetime, timedelta


class SocialIngestionError(Exception):
    """Base error exposed by every social provider adapter."""


class RateLimited(SocialIngestionError):
    def __init__(
        self,
        message: str = "social provider rate limited the request",
        *,
        retry_after: timedelta | None = None,
        retry_at: datetime | None = None,
    ) -> None:
        self.retry_after = retry_after
        self.retry_at = retry_at
        super().__init__(message)


class TransientProviderError(SocialIngestionError):
    pass


class InvalidSubscription(SocialIngestionError):
    pass


class PolicyDisabled(SocialIngestionError):
    pass


class PermanentProviderError(SocialIngestionError):
    pass

