from __future__ import annotations

import hashlib
import time
from datetime import UTC, date, datetime
from typing import Any, Mapping, Sequence

import httpx

from app.ingestion.fixtures.models import ExternalFixture
from app.ingestion.players.models import ExternalPlayer
from app.ingestion.stats.models import ExternalPlayerStat

from .models import (
    DEFAULT_FBREF_BASE_URL,
    DEFAULT_FBREF_CACHE_TTL_SECONDS,
    DEFAULT_FBREF_COMPETITION,
    DEFAULT_FBREF_COMPETITION_ID,
    DEFAULT_FBREF_RATE_LIMIT_RETRY_SECONDS,
    DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS,
    DEFAULT_FBREF_STAT_TYPES,
    DEFAULT_FBREF_USER_AGENT,
    FBREF_PROVIDER,
    FbrefPageCache,
    FbrefRawPage,
)
from .parser import parse_fixtures, parse_player_stats, parse_players


_STAT_PATHS: Mapping[str, str] = {
    "standard": "stats",
    "shooting": "shooting",
    "passing": "passing",
    "defense": "defense",
    "keeper": "keepers",
}
_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class FbrefError(Exception):
    pass


class FbrefClient:
    def __init__(
        self,
        base_url: str = DEFAULT_FBREF_BASE_URL,
        timeout_seconds: float = 15.0,
        request_interval_seconds: float = DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS,
        rate_limit_retry_seconds: float = DEFAULT_FBREF_RATE_LIMIT_RETRY_SECONDS,
        user_agent: str = DEFAULT_FBREF_USER_AGENT,
        cache_ttl_seconds: int = DEFAULT_FBREF_CACHE_TTL_SECONDS,
        page_cache: FbrefPageCache | None = None,
        transport: httpx.BaseTransport | None = None,
        sleeper: Any = time.sleep,
        clock: Any = time.monotonic,
        wall_clock: Any = lambda: datetime.now(UTC),
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._request_interval_seconds = request_interval_seconds
        self._rate_limit_retry_seconds = rate_limit_retry_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._page_cache = page_cache
        self._sleeper = sleeper
        self._clock = clock
        self._wall_clock = wall_clock
        self._last_request_at: float | None = None
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    @property
    def provider(self) -> str:
        return FBREF_PROVIDER

    def list_fixtures(
        self,
        league: int = DEFAULT_FBREF_COMPETITION_ID,
        season: int = 2025,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ExternalFixture]:
        source_url = self._fixture_url(league, season)
        page = self._get_page(source_url)
        fixtures = parse_fixtures(
            page.body,
            source_url=source_url,
            season=season,
            competition_id=league,
            competition=DEFAULT_FBREF_COMPETITION,
        )
        return [
            fixture
            for fixture in fixtures
            if _within_date_range(fixture.kickoff_at.date(), from_date, to_date)
        ]

    def list_league_players(
        self,
        league: int = DEFAULT_FBREF_COMPETITION_ID,
        season: int = 2025,
    ) -> list[ExternalPlayer]:
        source_url = self._stat_url(league, season, "standard")
        page = self._get_page(source_url)
        return parse_players(
            page.body,
            source_url=source_url,
            season=season,
            competition=DEFAULT_FBREF_COMPETITION,
        )

    def list_player_stats(
        self,
        league: int = DEFAULT_FBREF_COMPETITION_ID,
        season: int = 2025,
        stat_types: Sequence[str] | None = None,
    ) -> list[ExternalPlayerStat]:
        observations: list[ExternalPlayerStat] = []
        for stat_type in stat_types or DEFAULT_FBREF_STAT_TYPES:
            source_url = self._stat_url(league, season, stat_type)
            page = self._get_page(source_url)
            observations.extend(
                parse_player_stats(
                    page.body,
                    source_url=source_url,
                    season=season,
                    stat_type=stat_type,
                    competition_id=league,
                    competition=DEFAULT_FBREF_COMPETITION,
                )
            )
        return observations

    def _get_page(self, source_url: str) -> FbrefRawPage:
        cached = self._get_fresh_cached_page(source_url)
        if cached is not None:
            return cached

        response = self._request(source_url)
        body = response.text
        page = FbrefRawPage(
            provider=FBREF_PROVIDER,
            source_url=source_url,
            content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            body=body,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            fetched_at=self._wall_clock(),
        )
        if self._page_cache is not None:
            self._page_cache.save_page(page)
        return page

    def _get_fresh_cached_page(self, source_url: str) -> FbrefRawPage | None:
        if self._page_cache is None or self._cache_ttl_seconds <= 0:
            return None
        page = self._page_cache.get_latest_successful_page(source_url)
        if page is None:
            return None
        age = self._wall_clock() - page.fetched_at
        if age.total_seconds() > self._cache_ttl_seconds:
            return None
        return page

    def _request(self, source_url: str) -> httpx.Response:
        last_error: httpx.HTTPStatusError | None = None
        for attempt in range(3):
            self._throttle()
            response = self._client.get(source_url)
            if response.status_code not in _TRANSIENT_STATUS_CODES:
                response.raise_for_status()
                return response
            retry_after = _retry_after_seconds(
                response.headers.get("Retry-After"),
                self._rate_limit_retry_seconds * (attempt + 1),
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                last_error = error
            self._sleeper(retry_after)
            self._last_request_at = None
        if last_error is not None:
            raise last_error
        raise FbrefError(f"FBref request failed for {source_url}")

    def _throttle(self) -> None:
        if self._request_interval_seconds <= 0:
            self._last_request_at = self._clock()
            return

        now = self._clock()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            sleep_for = self._request_interval_seconds - elapsed
            if sleep_for > 0:
                self._sleeper(sleep_for)
                now = self._clock()
        self._last_request_at = now

    def _fixture_url(self, league: int, season: int) -> str:
        season_label = _season_label(season)
        return (
            f"{self._base_url}/en/comps/{league}/{season_label}/schedule/"
            f"{season_label}-Premier-League-Scores-and-Fixtures"
        )

    def _stat_url(self, league: int, season: int, stat_type: str) -> str:
        path = _STAT_PATHS.get(stat_type)
        if path is None:
            raise ValueError(f"unsupported FBref stat type: {stat_type}")
        season_label = _season_label(season)
        return (
            f"{self._base_url}/en/comps/{league}/{season_label}/{path}/"
            f"{season_label}-Premier-League-Stats"
        )


def _season_label(season: int) -> str:
    return f"{season}-{season + 1}"


def _within_date_range(
    fixture_date: date,
    from_date: date | None,
    to_date: date | None,
) -> bool:
    if from_date is not None and fixture_date < from_date:
        return False
    if to_date is not None and fixture_date > to_date:
        return False
    return True


def _retry_after_seconds(raw_value: str | None, default: float) -> float:
    if raw_value is None:
        return default
    try:
        return max(float(raw_value), 0.0)
    except ValueError:
        return default
