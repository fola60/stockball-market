from __future__ import annotations

import hashlib
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx
from curl_cffi import requests
from seleniumbase import SB

from app.ingestion.fixtures.models import ExternalFixture
from app.ingestion.players.models import ExternalPlayer
from app.ingestion.stats.models import ExternalPlayerStat
from app.seasons import resolve_season

from .models import (
    DEFAULT_FBREF_BASE_URL,
    DEFAULT_FBREF_CACHE_TTL_SECONDS,
    DEFAULT_FBREF_COMPETITION,
    DEFAULT_FBREF_COMPETITION_ID,
    DEFAULT_FBREF_RATE_LIMIT_RETRY_SECONDS,
    DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS,
    DEFAULT_FBREF_STAT_TYPES,
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
_DEBUG_DUMP_DIR = Path("/tmp/fbref-debug")
_ACCESS_DENIED_MARKERS = (
    "checking if the site connection is secure",
    "verify you are human",
    "cf-browser-verification",
    "just a moment...",
    "attention required!",
    "error 1020",
)


class FbrefError(Exception):
    pass

class FbrefAccessDeniedError(FbrefError):
    pass

class FbrefClient:
    def __init__(
        self,
        base_url: str = DEFAULT_FBREF_BASE_URL,
        timeout_seconds: float = 30.0, # Increased for browser emulation overhead
        request_interval_seconds: float = DEFAULT_FBREF_REQUEST_INTERVAL_SECONDS,
        rate_limit_retry_seconds: float = DEFAULT_FBREF_RATE_LIMIT_RETRY_SECONDS,
        cache_ttl_seconds: int = DEFAULT_FBREF_CACHE_TTL_SECONDS,
        page_cache: FbrefPageCache | None = None,
        use_host_chrome_for_browser: bool = True,
        host_chrome_binary_path: str | None = None,
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
        self._use_host_chrome_for_browser = use_host_chrome_for_browser
        self._host_chrome_binary_path = host_chrome_binary_path
        self._sleeper = sleeper
        self._clock = clock
        self._wall_clock = wall_clock
        self._last_request_at: float | None = None
        self._timeout_seconds = timeout_seconds
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if transport is None:
            self._session = requests.Session(
                base_url=self._base_url,
                impersonate="chrome124",
                timeout=timeout_seconds,
                headers=headers,
            )
        else:
            self._session = httpx.Client(
                base_url=self._base_url,
                transport=transport,
                timeout=timeout_seconds,
                headers=headers,
            )
        self._cookies_seeded = False

    def _request(self, source_url: str) -> requests.Response:
        print(f"[DEBUG] _request start: {source_url}")
        self._seed_cookies()

        for attempt in range(3):
            print(f"[DEBUG] Attempt {attempt + 1} for {source_url}")
            self._throttle()

            response = self._session.get(source_url)
            print(f"[DEBUG] Response status: {response.status_code}")
            if self._is_access_denied_response(response):
                debug_path = _save_debug_html(
                    f"debug_fbref_denied_attempt_{attempt + 1}.html",
                    response.text,
                )
                print(f"[DEBUG] Saved denied response page to {debug_path}")
            if self._is_successful_response(response):
                print("[DEBUG] Successful response")
                return response

            if self._is_access_denied_response(response):
                print("[DEBUG] Access denied detected")
                return self._request_with_browser(source_url)

            if response.status_code not in _TRANSIENT_STATUS_CODES:
                response.raise_for_status()
                return response

            print("[DEBUG] Transient error, retrying...")
            self._sleeper(self._get_retry_after(response, attempt))
            self._last_request_at = None

        raise FbrefError(f"FBref request failed after retries for {source_url}")

    def _seed_cookies(self) -> None:
        print("[DEBUG] Seeding cookies...")
        if self._cookies_seeded:
            return

        self._throttle()
        try:
            response = self._session.get("/")
        except Exception as exc:
            print(f"[DEBUG] Cookie seed failed, continuing without seeded cookies: {exc}")
            self._cookies_seeded = True
            return

        if response.status_code in {401, 403} or _looks_access_denied(response.text):
            print("[DEBUG] Cookie seed denied, continuing without browser fallback")
        else:
            print("[DEBUG] Cookie seed successful")
        self._cookies_seeded = True



    def _request_with_browser(self, source_url: str) -> requests.Response:
        print(f"[DEBUG] Browser fallback for {source_url}")
        try:
            browser_kwargs: dict[str, Any] = {
                "uc": True,
                "headless": False,
                "page_load_strategy": "eager",
            }
            if self._use_host_chrome_for_browser:
                browser_kwargs["binary_location"] = self._host_chrome_binary_path or _default_host_chrome_binary_path()
                print(f"[DEBUG] Using host Chrome binary: {browser_kwargs['binary_location']}")

            with SB(**browser_kwargs) as browser:
                browser.open(source_url)
                body = self._wait_for_browser_page(browser)
                print("[DEBUG] Browser finished loading page")
                for cookie in browser.get_cookies():
                    name = cookie.get("name")
                    value = cookie.get("value")
                    if name and value is not None:
                        self._session.cookies.set(name, value, domain=".fbref.com")
        except Exception as exc:
            raise FbrefError(
                f"FBref browser fallback failed for {source_url}"
            ) from exc

        if _looks_access_denied(body):
            debug_path = _save_debug_html("debug_fbref_denied.html", body)
            print(f"[DEBUG] Saved denied browser page to {debug_path}")
            raise FbrefAccessDeniedError(
                "FBref denied access. Possible bot detection or IP ban. "
                f"url={source_url}"
            )

        if not _looks_like_fbref_page(body):
            debug_path = _save_debug_html("debug_fbref_unexpected.html", body)
            print(f"[DEBUG] Saved unexpected browser page to {debug_path}")
            raise FbrefAccessDeniedError(
                "FBref browser fallback did not return a valid FBref page. "
                "The page may still be behind bot protection, consent, or JavaScript. "
                f"url={source_url}; body_length={len(body)}"
            )

        print("[DEBUG] Browser page looks like a valid FBref page")
        debug_path = _save_debug_html("debug_fbref_success.html", body)
        print(f"[DEBUG] Saved successful browser page to {debug_path}")
        response = requests.Response()
        response.status_code = 200
        response.url = source_url
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.content = body.encode("utf-8")
        return response

    def _wait_for_browser_page(self, browser: Any) -> str:
        deadline = time.monotonic() + self._timeout_seconds
        body = str(browser.get_page_source())
        while not _browser_page_is_ready(body):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            browser.sleep(min(1.0, remaining))
            body = str(browser.get_page_source())
        return body

        

    def _is_successful_response(self, response: requests.Response) -> bool:
        print(f"[DEBUG] Checking success for status {response.status_code}")
        return (
            response.status_code not in _TRANSIENT_STATUS_CODES
            and response.status_code not in {401, 403}
            and not _looks_access_denied(response.text)
        )

    def _is_access_denied_response(self, response: requests.Response) -> bool:
        return response.status_code in {401, 403} or _looks_access_denied(response.text)

    def _get_retry_after(self, response: requests.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After")
        if header and header.isdigit():
            return float(header)
        return self._rate_limit_retry_seconds * (attempt + 1)


    def _throttle(self) -> None:
        print("[DEBUG] Throttling request...")
        if self._request_interval_seconds <= 0:
            self._last_request_at = self._clock()
            return

        now = self._clock()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            # FBref requires ~6.0s for the 10-per-minute rule
            sleep_for = self._request_interval_seconds - elapsed
            if sleep_for > 0:
                self._sleeper(sleep_for)
                now = self._clock()
        self._last_request_at = now

    @property
    def provider(self) -> str:
        return FBREF_PROVIDER

    def list_fixtures(
        self,
        league: int = DEFAULT_FBREF_COMPETITION_ID,
        season: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ExternalFixture]:
        season = resolve_season(season)
        print(f"[DEBUG] list_fixtures: league={league}, season={season}")
        source_url = self._fixture_url(league, season)
        page = self._get_page(source_url)
        fixtures = parse_fixtures(
            page.body,
            source_url=source_url,
            season=season,
            competition_id=league,
            competition=DEFAULT_FBREF_COMPETITION,
        )
        print(f"[DEBUG] Parsed fixtures before date filtering: {len(fixtures)}")
        print(f"[DEBUG] Date filters: from_date={from_date}, to_date={to_date}")
        filtered_fixtures = [
            fixture
            for fixture in fixtures
            if _within_date_range(fixture.kickoff_at.date(), from_date, to_date)
        ]
        print(f"[DEBUG] Fixtures after date filtering: {len(filtered_fixtures)}")
        return filtered_fixtures

    def list_league_players(
        self,
        league: int = DEFAULT_FBREF_COMPETITION_ID,
        season: int | None = None,
    ) -> list[ExternalPlayer]:
        season = resolve_season(season)
        print(f"[DEBUG] list_league_players: league={league}, season={season}")
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
        season: int | None = None,
        stat_types: Sequence[str] | None = None,
    ) -> list[ExternalPlayerStat]:
        season = resolve_season(season)
        print(f"[DEBUG] list_player_stats: league={league}, season={season}")
        observations: list[ExternalPlayerStat] = []
        for stat_type in stat_types or DEFAULT_FBREF_STAT_TYPES:
            print(f"[DEBUG] Fetching stat_type={stat_type}")
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
        print(f"[DEBUG] _get_page called for {source_url}")
        cached = self._get_fresh_cached_page(source_url)
        if cached is not None:
            print("[DEBUG] Cache hit")
            return cached

        print(f"[DEBUG] Cache miss, fetching: {source_url}")
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


def _default_host_chrome_binary_path() -> str:
    candidates = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise FbrefError(
        "Host Chrome was requested, but no Chrome binary was found. "
        "Pass host_chrome_binary_path explicitly."
    )

def _looks_like_fbref_page(body: str) -> bool:
    lowered = body.lower()
    fbref_markers = (
        "fbref.com",
        "sports-reference",
        "data-stat=",
        "scores & fixtures",
        "scores and fixtures",
        "premier league scores and fixtures",
        "standard stats",
        "shooting stats",
        "passing stats",
        "defense stats",
        "goalkeeping stats",
    )
    matched_markers = [marker for marker in fbref_markers if marker in lowered]
    if matched_markers:
        print(f"[DEBUG] FBref page markers matched: {matched_markers}")
        return True
    return False


def _looks_access_denied(body: str) -> bool:
    lowered = body.lower()
    matched_markers = [marker for marker in _ACCESS_DENIED_MARKERS if marker in lowered]
    if matched_markers:
        print(f"[DEBUG] Access denied markers matched: {matched_markers}")
        return True
    return False


def _browser_page_is_ready(body: str) -> bool:
    lowered = body.lower()
    return "data-stat=" in lowered and not any(
        marker in lowered for marker in _ACCESS_DENIED_MARKERS
    )


def _save_debug_html(filename: str, body: str) -> Path:
    _DEBUG_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    debug_path = _DEBUG_DUMP_DIR / filename
    debug_path.write_text(body, encoding="utf-8")
    return debug_path.resolve()
