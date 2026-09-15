from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


class ArticleFetchSkipped(Exception):
    """The target is permanently unsuitable for article enrichment."""


class ArticleFetchTransient(Exception):
    """The target may succeed on a later bounded retry."""


@dataclass(frozen=True)
class ArticleFetchResult:
    content: bytes
    final_url: str
    status_code: int
    content_type: str


class ArticleFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_redirects: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_redirects = max(max_redirects, 0)
        self._transport = transport

    def fetch(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
        max_response_bytes: int,
    ) -> ArticleFetchResult:
        _validate_url(url, allowed_hosts)
        current_url = url
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "StockballSocialEnrichment/1.0",
        }
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                for redirect_count in range(self._max_redirects + 1):
                    response = client.get(current_url, headers=headers)
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    if redirect_count >= self._max_redirects:
                        raise ArticleFetchSkipped("article exceeded its redirect limit")
                    location = response.headers.get("location")
                    if not location:
                        raise ArticleFetchSkipped("article redirect omitted Location")
                    current_url = urljoin(current_url, location)
                    _validate_url(current_url, allowed_hosts)
                else:  # pragma: no cover - loop exits through break or raise
                    raise ArticleFetchSkipped("article redirect loop")
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise ArticleFetchTransient("article request failed") from error

        if response.status_code == 429 or response.status_code >= 500:
            raise ArticleFetchTransient(f"article returned HTTP {response.status_code}")
        if response.status_code != 200:
            raise ArticleFetchSkipped(f"article returned HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ArticleFetchSkipped(f"article content type {content_type or 'unknown'} is not HTML")
        if len(response.content) > max(max_response_bytes, 1):
            raise ArticleFetchSkipped("article exceeds its approved response-size limit")
        return ArticleFetchResult(
            content=response.content,
            final_url=str(response.url),
            status_code=response.status_code,
            content_type=content_type,
        )


def _validate_url(url: str, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    allowed = {value.casefold() for value in allowed_hosts}
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ArticleFetchSkipped("article URL must be HTTPS without credentials")
    if host not in allowed:
        raise ArticleFetchSkipped(f"article host {host!r} is not approved")
