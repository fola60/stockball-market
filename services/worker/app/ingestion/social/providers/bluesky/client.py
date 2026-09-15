from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Mapping

import httpx

from ...domain import (
    InvalidSubscription,
    PermanentProviderError,
    RateLimited,
    RateLimitState,
    TransientProviderError,
)

PUBLIC_APPVIEW_URL = "https://public.api.bsky.app"


class BlueskyClient:
    def __init__(
        self,
        *,
        base_url: str = PUBLIC_APPVIEW_URL,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    async def resolve_handle(self, handle: str) -> str:
        payload, _ = await self._get(
            "/xrpc/com.atproto.identity.resolveHandle", {"handle": handle}
        )
        did = payload.get("did")
        if not isinstance(did, str) or not did.startswith("did:"):
            raise PermanentProviderError("Bluesky returned an invalid DID")
        return did

    async def get_author_feed(
        self,
        actor: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[Mapping[str, object], RateLimitState | None]:
        params: dict[str, str | int] = {
            "actor": actor,
            "limit": min(max(limit, 1), 100),
            "filter": "posts_with_replies",
        }
        if cursor:
            params["cursor"] = cursor
        return await self._get("/xrpc/app.bsky.feed.getAuthorFeed", params)

    async def _get(
        self, path: str, params: Mapping[str, str | int]
    ) -> tuple[Mapping[str, object], RateLimitState | None]:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.get(f"{self._base_url}{path}", params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise TransientProviderError("Bluesky request failed") from error
        rate_limit = _rate_limit(response.headers)
        if response.status_code == 429:
            raise RateLimited(
                "Bluesky rate limited the request",
                retry_after=_retry_after(response.headers),
                retry_at=rate_limit.reset_at if rate_limit else None,
            )
        if response.status_code >= 500:
            raise TransientProviderError(f"Bluesky temporary failure: HTTP {response.status_code}")
        if response.status_code in {400, 404, 422}:
            raise InvalidSubscription(f"Bluesky rejected the subscription: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise PermanentProviderError(f"Bluesky request failed: HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise TransientProviderError("Bluesky returned malformed JSON") from error
        if not isinstance(payload, Mapping):
            raise TransientProviderError("Bluesky returned a non-object response")
        return payload, rate_limit


def _rate_limit(headers: httpx.Headers) -> RateLimitState | None:
    limit = _optional_int(headers.get("ratelimit-limit") or headers.get("x-ratelimit-limit"))
    remaining = _optional_int(
        headers.get("ratelimit-remaining") or headers.get("x-ratelimit-remaining")
    )
    reset_at = _reset_at(headers.get("ratelimit-reset") or headers.get("x-ratelimit-reset"))
    if limit is remaining is None and reset_at is None:
        return None
    return RateLimitState(limit=limit, remaining=remaining, reset_at=reset_at)


def _retry_after(headers: httpx.Headers) -> timedelta | None:
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return timedelta(seconds=max(float(raw), 0))
    except ValueError:
        try:
            value = parsedate_to_datetime(raw)
            return max(value.astimezone(UTC) - datetime.now(UTC), timedelta())
        except (TypeError, ValueError):
            return None


def _optional_int(value: str | None) -> int | None:
    try:
        return None if value is None else int(value)
    except ValueError:
        return None


def _reset_at(value: str | None) -> datetime | None:
    try:
        if value is None:
            return None
        numeric = float(value)
        # Some implementations expose delta seconds, others a Unix timestamp.
        return (
            datetime.fromtimestamp(numeric, UTC)
            if numeric > 10_000_000
            else datetime.now(UTC) + timedelta(seconds=numeric)
        )
    except (ValueError, OverflowError, OSError):
        return None

