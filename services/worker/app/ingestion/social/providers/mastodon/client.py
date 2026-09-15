from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping
from urllib.parse import urlparse

import httpx

from ...domain import InvalidSubscription, RateLimited, RateLimitState, TransientProviderError


class MastodonClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._transport = transport

    async def account_statuses(
        self,
        instance_url: str,
        account_id: str,
        *,
        since_id: str | None = None,
        limit: int = 40,
        access_token: str | None = None,
    ) -> tuple[list[Mapping[str, object]], RateLimitState | None]:
        parsed = urlparse(instance_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise InvalidSubscription("Mastodon instance must be an HTTPS origin")
        params: dict[str, str | int] = {
            "limit": min(max(limit, 1), 40),
            "exclude_reblogs": "true",
        }
        if since_id:
            params["since_id"] = since_id
        headers = {} if not access_token else {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport, follow_redirects=False
            ) as client:
                response = await client.get(
                    f"{instance_url.rstrip('/')}/api/v1/accounts/{account_id}/statuses",
                    params=params,
                    headers=headers,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise TransientProviderError("Mastodon request failed") from error
        rate_limit = _rate_limit(response.headers)
        if response.status_code == 429:
            retry_at = None if rate_limit is None else rate_limit.reset_at
            raise RateLimited("Mastodon instance rate limited the request", retry_at=retry_at)
        if response.status_code >= 500:
            raise TransientProviderError(
                f"Mastodon instance temporary failure: HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise InvalidSubscription(
                f"Mastodon account timeline is unavailable: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise TransientProviderError("Mastodon returned malformed JSON") from error
        if not isinstance(payload, list) or not all(isinstance(item, Mapping) for item in payload):
            raise TransientProviderError("Mastodon returned malformed status data")
        return list(payload), rate_limit


def _rate_limit(headers: httpx.Headers) -> RateLimitState | None:
    try:
        limit = int(headers["x-ratelimit-limit"])
    except (KeyError, ValueError):
        limit = None
    try:
        remaining = int(headers["x-ratelimit-remaining"])
    except (KeyError, ValueError):
        remaining = None
    try:
        raw_reset = headers["x-ratelimit-reset"]
        reset_at = datetime.fromisoformat(raw_reset.replace("Z", "+00:00")).astimezone(UTC)
    except (KeyError, ValueError):
        reset_at = None
    if limit is remaining is None and reset_at is None:
        return None
    return RateLimitState(limit=limit, remaining=remaining, reset_at=reset_at)
