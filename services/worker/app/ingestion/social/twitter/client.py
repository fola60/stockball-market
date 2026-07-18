from __future__ import annotations

import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Mapping

import httpx

from .models import TwitterPost, TwitterRateLimit, TwitterSearchPage


TWITTER_API_BASE_URL = "https://api.x.com"


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
    """Approved X API v2 recent-search client. This client contains no scraper."""

    def __init__(
        self,
        bearer_token: str | None,
        *,
        policy_acknowledged: bool = False,
        base_url: str = TWITTER_API_BASE_URL,
        timeout_seconds: float = 15.0,
        request_interval_seconds: float = 1.0,
        max_rate_limit_sleep_seconds: float = 60.0,
        max_results: int = 100,
        transport: httpx.BaseTransport | None = None,
        sleeper: Any = time.sleep,
        monotonic_clock: Any = time.monotonic,
        utc_clock: Any = lambda: datetime.now(UTC),
    ) -> None:
        self._bearer_token = bearer_token
        self._policy_acknowledged = policy_acknowledged
        self._request_interval_seconds = max(request_interval_seconds, 0.0)
        self._max_rate_limit_sleep_seconds = max(max_rate_limit_sleep_seconds, 0.0)
        self._max_results = min(max(max_results, 10), 100)
        self._sleeper = sleeper
        self._monotonic_clock = monotonic_clock
        self._utc_clock = utc_clock
        self._last_request_at: float | None = None
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {bearer_token or ''}",
            },
            timeout=timeout_seconds,
            transport=transport,
        )

    def search_page(
        self,
        query: str,
        *,
        since_id: str | None = None,
        next_token: str | None = None,
    ) -> TwitterSearchPage:
        if not self._bearer_token:
            raise TwitterSourceDisabledError(
                "X ingestion is disabled; configure STOCKBALL_TWITTER_BEARER_TOKEN"
            )
        if not self._policy_acknowledged:
            raise TwitterSourceDisabledError(
                "X ingestion requires STOCKBALL_TWITTER_POLICY_ACKNOWLEDGED=true after "
                "approved-use-case and data-policy review"
            )
        params = {
            "query": query,
            "max_results": str(self._max_results),
            "sort_order": "recency",
            "tweet.fields": (
                "author_id,created_at,lang,conversation_id,referenced_tweets,"
                "edit_history_tweet_ids"
            ),
        }
        if since_id:
            params["since_id"] = since_id
        if next_token:
            params["next_token"] = next_token

        response = self._request(params)
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise TwitterIngestionError("X recent-search response must be a JSON object")
        return _parse_search_page(payload, response.headers)

    def _request(self, params: Mapping[str, str]) -> httpx.Response:
        for attempt in range(2):
            self._throttle()
            response = self._client.get("/2/tweets/search/recent", params=params)
            if response.status_code in {401, 403}:
                raise TwitterAccessDeniedError("X API rejected the configured bearer token or access tier")
            if response.status_code == 429:
                reset_at = _rate_limit(response.headers).reset_at
                wait_seconds = _retry_wait_seconds(
                    response.headers,
                    reset_at,
                    now=self._utc_clock(),
                )
                if attempt == 0 and wait_seconds <= self._max_rate_limit_sleep_seconds:
                    self._sleeper(max(wait_seconds, 0.0))
                    continue
                raise TwitterRateLimitError("X recent-search rate limit reached", reset_at)
            if response.status_code >= 500:
                raise TwitterTransientError(f"X recent-search temporary failure: HTTP {response.status_code}")
            response.raise_for_status()
            return response
        raise TwitterTransientError("X recent-search request did not complete")

    def _throttle(self) -> None:
        now = self._monotonic_clock()
        if self._last_request_at is not None:
            wait = self._request_interval_seconds - (now - self._last_request_at)
            if wait > 0:
                self._sleeper(wait)
                now = self._monotonic_clock()
        self._last_request_at = now


def _parse_search_page(
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
) -> TwitterSearchPage:
    posts: list[TwitterPost] = []
    data = payload.get("data", [])
    if data is None:
        data = []
    if not isinstance(data, list):
        raise TwitterIngestionError("X recent-search data must be a list")
    for raw_post in data:
        if not isinstance(raw_post, Mapping):
            continue
        post_id = raw_post.get("id")
        author_id = raw_post.get("author_id")
        text = raw_post.get("text")
        created_at = raw_post.get("created_at")
        if None in {post_id, author_id, text, created_at}:
            continue
        posts.append(
            TwitterPost(
                post_id=str(post_id),
                author_id=str(author_id),
                text=str(text),
                created_at=_timestamp(created_at),
                lang=_optional_string(raw_post.get("lang")),
                conversation_id=_optional_string(raw_post.get("conversation_id")),
                referenced_post_ids=tuple(
                    str(ref["id"])
                    for ref in raw_post.get("referenced_tweets", [])
                    if isinstance(ref, Mapping) and ref.get("id") is not None
                ),
                edit_history_post_ids=tuple(
                    str(value) for value in raw_post.get("edit_history_tweet_ids", [])
                ),
            )
        )
    meta = payload.get("meta", {})
    if not isinstance(meta, Mapping):
        meta = {}
    return TwitterSearchPage(
        posts=tuple(posts),
        newest_id=_optional_string(meta.get("newest_id")),
        next_token=_optional_string(meta.get("next_token")),
        rate_limit=_rate_limit(headers),
    )


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _rate_limit(headers: Mapping[str, str]) -> TwitterRateLimit:
    return TwitterRateLimit(
        limit=_optional_int(headers.get("x-rate-limit-limit")),
        remaining=_optional_int(headers.get("x-rate-limit-remaining")),
        reset_at=_reset_timestamp(headers.get("x-rate-limit-reset")),
    )


def _retry_wait_seconds(
    headers: Mapping[str, str],
    reset_at: datetime | None,
    *,
    now: datetime,
) -> float:
    retry_after = headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            try:
                return max((parsedate_to_datetime(retry_after) - now).total_seconds(), 0.0)
            except (TypeError, ValueError):
                pass
    if reset_at is not None:
        return max((reset_at - now).total_seconds(), 0.0) + 1.0
    return 60.0


def _optional_int(value: object) -> int | None:
    try:
        return None if value is None else int(str(value))
    except ValueError:
        return None


def _reset_timestamp(value: object) -> datetime | None:
    try:
        return None if value is None else datetime.fromtimestamp(int(str(value)), tz=UTC)
    except (ValueError, OSError):
        return None
