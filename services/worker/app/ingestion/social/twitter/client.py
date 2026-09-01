from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.parse import quote, urlencode
from urllib.parse import urlparse

import httpx

from app.ingestion.fetch import (
    ContentFetchService,
    FetchRequest,
    FetchResponseError,
    FetchUnavailableError,
)

from .models import TwitterRateLimit, TwitterSearchPage
from .parser import parse_search_page_html


TWITTER_SEARCH_BASE_URL = "https://x.com"


class TwitterIngestionError(Exception):
    pass


class TwitterSourceDisabledError(TwitterIngestionError):
    pass


class TwitterAccessDeniedError(TwitterIngestionError):
    pass


class TwitterTransientError(TwitterIngestionError):
    pass


class TwitterRateLimitError(TwitterTransientError):
    def __init__(self, message: str, reset_at: datetime | None = None) -> None:
        self.reset_at = reset_at
        super().__init__(message)


class TwitterRecentSearchClient:
    """Browser-based X search client that scrapes rendered HTML pages."""

    def __init__(
        self,
        *,
        policy_acknowledged: bool = False,
        base_url: str = TWITTER_SEARCH_BASE_URL,
        timeout_seconds: float = 30.0,
        request_interval_seconds: float = 2.0,
        max_results: int = 20,
        browser_enabled: bool = False,
        use_host_chrome: bool = True,
        host_chrome_binary_path: str | None = None,
        browser_user_data_dir: str | None = None,
        browser_profile_directory: str | None = None,
        browser_idle_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
        sleeper: Any = time.sleep,
        monotonic_clock: Any = time.monotonic,
        utc_clock: Any = lambda: datetime.now(UTC),
    ) -> None:
        self._policy_acknowledged = policy_acknowledged
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._request_interval_seconds = max(request_interval_seconds, 0.0)
        self._max_results = max(max_results, 1)
        self._sleeper = sleeper
        self._monotonic_clock = monotonic_clock
        self._utc_clock = utc_clock
        self._last_request_at: float | None = None
        self._allowed_hosts = (urlparse(self._base_url).hostname or "",)
        self._fetcher = ContentFetchService(
            transport=transport,
            browser_enabled=browser_enabled,
            use_host_chrome=use_host_chrome,
            host_chrome_binary_path=host_chrome_binary_path,
            browser_user_data_dir=browser_user_data_dir,
            browser_profile_directory=browser_profile_directory,
            browser_idle_seconds=browser_idle_seconds,
        )

    def search_page(
        self,
        query: str,
        *,
        since_id: str | None = None,
        next_token: str | None = None,
    ) -> TwitterSearchPage:
        if not self._policy_acknowledged:
            raise TwitterSourceDisabledError(
                "X ingestion requires STOCKBALL_TWITTER_POLICY_ACKNOWLEDGED=true after "
                "approved-use-case and data-policy review"
            )

        return self._request(query, since_id=since_id)

    def _request(
        self,
        query: str,
        *,
        since_id: str | None = None,
    ) -> TwitterSearchPage:
        self._throttle()

        params = {"q": query, "src": "typed_query", "f": "live"}
        url = f"{self._base_url}/search?{urlencode(params, quote_via=quote)}"
        request = FetchRequest(
            url=url,
            allowed_hosts=self._allowed_hosts,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            accepted_content_types=("text/html",),
            timeout_seconds=self._timeout_seconds,
            browser_wait_selector='article[data-testid="tweet"]',
            # X returns a JavaScript shell with HTTP 200 to normal clients; use the
            # selected signed-in Chrome profile before attempting to parse it.
            prefer_browser=True,
        )

        try:
            fetched = self._fetcher.fetch(request)
        except FetchResponseError as exc:
            status = exc.status_code
            if status in {401, 403}:
                raise TwitterAccessDeniedError(
                    "X denied access to the search page; check browser session cookies"
                ) from exc
            if status is not None and status >= 500:
                raise TwitterTransientError(
                    f"X search temporary failure: HTTP {status}"
                ) from exc
            raise TwitterIngestionError(
                f"X search failed: HTTP {status}"
            ) from exc
        except FetchUnavailableError as exc:
            raise TwitterTransientError("X search request failed") from exc

        html = fetched.content.decode("utf-8", errors="replace")
        if not html or "<article" not in html:
            raise TwitterIngestionError(
                "X search response did not contain tweet articles"
            )

        return parse_search_page_html(html, since_id=since_id)

    def _throttle(self) -> None:
        now = self._monotonic_clock()
        if self._last_request_at is not None:
            wait = self._request_interval_seconds - (now - self._last_request_at)
            if wait > 0:
                self._sleeper(wait)
                now = self._monotonic_clock()
        self._last_request_at = now
