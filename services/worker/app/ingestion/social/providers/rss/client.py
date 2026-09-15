from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urljoin, urlparse

import httpx

from ...domain import (
    InvalidSubscription,
    PermanentProviderError,
    RateLimited,
    TransientProviderError,
)


@dataclass(frozen=True)
class FeedResponse:
    status_code: int
    content: bytes
    headers: Mapping[str, str]
    final_url: str


class RssClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        max_response_bytes: int = 2_000_000,
        max_redirects: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_response_bytes = max(max_response_bytes, 1)
        self._max_redirects = max(max_redirects, 0)
        self._transport = transport

    async def fetch(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FeedResponse:
        _validate_url(url, allowed_hosts)
        headers = {"Accept": "application/atom+xml,application/rss+xml,application/xml,text/xml"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        current_url = url
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                for redirect_count in range(self._max_redirects + 1):
                    response = await client.get(current_url, headers=headers)
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    if redirect_count >= self._max_redirects:
                        raise InvalidSubscription("RSS feed exceeded its redirect limit")
                    location = response.headers.get("location")
                    if not location:
                        raise InvalidSubscription("RSS redirect omitted Location")
                    current_url = urljoin(current_url, location)
                    _validate_url(current_url, allowed_hosts)
                else:  # pragma: no cover - loop always exits through break/raise
                    raise InvalidSubscription("RSS redirect loop")
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise TransientProviderError("RSS request failed") from error
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            from datetime import timedelta

            try:
                delay = timedelta(seconds=max(float(retry_after or ""), 0))
            except ValueError:
                delay = None
            raise RateLimited("RSS publisher rate limited the request", retry_after=delay)
        if response.status_code >= 500:
            raise TransientProviderError(f"RSS publisher temporary failure: HTTP {response.status_code}")
        if response.status_code in {401, 403, 404, 410}:
            raise InvalidSubscription(f"RSS feed is unavailable: HTTP {response.status_code}")
        if response.status_code not in {200, 304}:
            raise PermanentProviderError(f"RSS request failed: HTTP {response.status_code}")
        content = response.content
        if len(content) > self._max_response_bytes:
            raise PermanentProviderError("RSS response exceeds the configured size limit")
        return FeedResponse(
            status_code=response.status_code,
            content=content,
            headers=dict(response.headers),
            final_url=str(response.url),
        )


def _validate_url(url: str, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    allowed = {value.casefold() for value in allowed_hosts}
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise InvalidSubscription("RSS feed URL must be an HTTP(S) URL without credentials")
    if host not in allowed:
        raise InvalidSubscription(f"RSS redirect host {host!r} is not approved")

