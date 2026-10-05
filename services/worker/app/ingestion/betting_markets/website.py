from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from app.ingestion.fetch import ContentFetchService, FetchResponseError, FetchUnavailableError

from .errors import Bet365IngestionError, Bet365SourceDisabledError
from .models import (
    BET365_PROVIDER,
    Bet365CompetitionDiscovery,
    Bet365DiscoveredFixture,
    Bet365FixtureListing,
    BettingMarketObservation,
)
from .parsing import (
    _MARKET_TITLE,
    _competition_name,
    _competition_navigation_labels,
    _exact_text_xpath,
    _fixture_row_xpath,
    _required_text,
    _with_fixture_context,
    parse_competition_fixture_listings,
    parse_website_match_1x2,
    parse_website_player_markets,
    provider_event_id_from_url,
)

LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


DEFAULT_BET365_HOMEPAGE_URL = "https://www.bet365.com/#/HO/"
DEFAULT_BET365_COMPETITION_NAME = "Premier League"
_COOKIE_ACCEPT_XPATH = "//button[normalize-space(.)='Accept All']"


class Bet365Client:
    """Discovers and refreshes Bet365 event pages through an enabled browser session."""

    def __init__(
        self,
        *,
        browser_enabled: bool,
        homepage_url: str = DEFAULT_BET365_HOMEPAGE_URL,
        competition_name: str = DEFAULT_BET365_COMPETITION_NAME,
        max_matches: int = 20,
        pre_match_cutoff_minutes: int = 5,
        request_interval_seconds: float = 60.0,
        timeout_seconds: float = 20.0,
        browser_idle_seconds: float = 3.0,
        use_host_chrome: bool = True,
        host_chrome_binary_path: str | None = None,
        browser_user_data_dir: str | None = None,
        browser_profile_directory: str | None = None,
        browser_factory: Callable[..., object] | None = None,
        sleeper: Any = time.sleep,
        clock: Any = time.monotonic,
        utc_clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        parsed_homepage = urlparse(homepage_url)
        if parsed_homepage.scheme not in {"http", "https"} or not parsed_homepage.hostname:
            raise ValueError("Bet365 homepage URL must be an absolute HTTP(S) URL")
        if max_matches <= 0:
            raise ValueError("Bet365 website max_matches must be positive")
        if pre_match_cutoff_minutes < 0:
            raise ValueError("Bet365 pre-match cutoff cannot be negative")

        self._browser_enabled = browser_enabled
        self._homepage_url = homepage_url
        self._competition_name = _required_text(competition_name, "competition_name")
        self._max_matches = max_matches
        self._pre_match_cutoff = timedelta(minutes=pre_match_cutoff_minutes)
        self._request_interval_seconds = max(request_interval_seconds, 0.0)
        self._timeout_seconds = timeout_seconds
        self._browser_idle_seconds = max(browser_idle_seconds, 0.0)
        self._allowed_hosts = (parsed_homepage.hostname,)
        self._sleeper = sleeper
        self._clock = clock
        self._utc_clock = utc_clock
        self._last_navigation_at: float | None = None
        self._fetcher = ContentFetchService(
            browser_enabled=browser_enabled,
            use_undetected_chrome=True,
            use_host_chrome=use_host_chrome,
            host_chrome_binary_path=host_chrome_binary_path,
            browser_idle_seconds=browser_idle_seconds,
            browser_factory=browser_factory,
            browser_user_data_dir=browser_user_data_dir,
            browser_profile_directory=browser_profile_directory,
            browser_locale_code="en-GB",
        )

    @property
    def provider(self) -> str:
        return BET365_PROVIDER

    def discover_pre_match_pages(
        self,
        league: str | None = None,
    ) -> Bet365CompetitionDiscovery:
        discovery, _ = self._crawl(league, parse_markets=False)
        return discovery

    def list_pre_match_1x2(self, league: str | None = None) -> list[BettingMarketObservation]:
        _, observations = self._crawl(
            league,
            parse_markets=True,
            include_player_markets=False,
        )
        return observations

    def list_pre_match_markets(
        self,
        league: str | None = None,
    ) -> list[BettingMarketObservation]:
        _, observations = self._crawl(
            league,
            parse_markets=True,
            include_player_markets=True,
        )
        return observations

    def list_live_markets(
        self,
        fixtures: tuple[Bet365DiscoveredFixture, ...],
    ) -> list[BettingMarketObservation]:
        if not fixtures:
            return []
        self._assert_enabled()
        observations: list[BettingMarketObservation] = []
        failures = 0

        try:
            with self._fetcher.browser_session(allowed_hosts=self._allowed_hosts) as browser:
                targets = fixtures[: self._max_matches]
                for fixture in targets:
                    try:
                        page_html = self._open_event_url(browser, fixture)
                        observations.extend(
                            self._parse_fixture_markets(
                                page_html,
                                fixture,
                                include_player_markets=True,
                                require_match_result=False,
                            )
                        )
                    except (
                        Bet365IngestionError,
                        FetchResponseError,
                        FetchUnavailableError,
                        LookupError,
                        TimeoutError,
                    ) as exc:
                        failures += 1
                        LOGGER.warning(
                            "Bet365 live refresh failed for %s vs %s: %s",
                            fixture.home_team,
                            fixture.away_team,
                            exc,
                        )
        except Bet365IngestionError:
            raise
        except (FetchResponseError, FetchUnavailableError, LookupError, TimeoutError) as exc:
            raise Bet365IngestionError(f"Bet365 website browser session failed: {exc}") from exc

        if failures == len(targets):
            raise Bet365IngestionError("Bet365 could not refresh any active event pages")
        return observations

    def _crawl(
        self,
        league: str | None,
        *,
        parse_markets: bool,
        include_player_markets: bool = False,
    ) -> tuple[Bet365CompetitionDiscovery, list[BettingMarketObservation]]:
        self._assert_enabled()
        competition_name = _competition_name(league, self._competition_name)
        observations: list[BettingMarketObservation] = []
        discovered: list[Bet365DiscoveredFixture] = []
        failures = 0

        try:
            with self._fetcher.browser_session(allowed_hosts=self._allowed_hosts) as browser:
                competition_url, listings = self._open_competition(browser, competition_name)
                for listing in listings[: self._max_matches]:
                    try:
                        fixture, page_html = self._open_fixture(browser, competition_url, listing)
                        discovered.append(fixture)
                        if parse_markets:
                            observations.extend(
                                self._parse_fixture_markets(
                                    page_html,
                                    fixture,
                                    include_player_markets=include_player_markets,
                                    require_match_result=True,
                                )
                            )
                    except (
                        Bet365IngestionError,
                        FetchResponseError,
                        FetchUnavailableError,
                        LookupError,
                        TimeoutError,
                    ) as exc:
                        failures += 1
                        LOGGER.warning(
                            "Bet365 fixture discovery failed for %s vs %s: %s",
                            listing.home_team,
                            listing.away_team,
                            exc,
                        )
        except Bet365IngestionError:
            raise
        except (FetchResponseError, FetchUnavailableError, LookupError, TimeoutError) as exc:
            raise Bet365IngestionError(f"Bet365 website browser session failed: {exc}") from exc

        if listings and not discovered:
            raise Bet365IngestionError(
                f"Bet365 website listed {len(listings)} fixtures but none could be opened"
            )
        if parse_markets and discovered and not observations:
            raise Bet365IngestionError(
                f"Bet365 opened {len(discovered)} fixtures but found no Full Time Result markets"
            )
        if failures:
            LOGGER.warning(
                "Bet365 website crawl completed with %s failed fixture pages",
                failures,
            )

        return (
            Bet365CompetitionDiscovery(
                competition_name=competition_name,
                competition_url=competition_url,
                fixtures=tuple(discovered),
            ),
            observations,
        )

    def _parse_fixture_markets(
        self,
        page_html: str,
        fixture: Bet365DiscoveredFixture,
        *,
        include_player_markets: bool,
        require_match_result: bool,
    ) -> list[BettingMarketObservation]:
        observed_at = self._utc_clock()
        observations: list[BettingMarketObservation] = []
        try:
            observations.extend(
                parse_website_match_1x2(
                    page_html,
                    source_url=fixture.source_url,
                    observed_at=observed_at,
                    expected_home_team=fixture.home_team,
                    expected_away_team=fixture.away_team,
                )
            )
        except Bet365IngestionError:
            if require_match_result:
                raise
        if include_player_markets:
            observations.extend(
                parse_website_player_markets(
                    page_html,
                    source_url=fixture.source_url,
                    observed_at=observed_at,
                )
            )
        return [_with_fixture_context(observation, fixture) for observation in observations]

    def _open_competition(
        self,
        browser: Any,
        competition_name: str,
    ) -> tuple[str, list[Bet365FixtureListing]]:
        labels = _competition_navigation_labels(competition_name)
        try:
            self._open_football_hub(browser, labels)
        except (Bet365IngestionError, LookupError, TimeoutError):
            pass
        result = self._try_open_competition_from_current_page(browser, labels)
        if result is not None:
            return result

        raise Bet365IngestionError(
            f"Bet365 competition link {competition_name!r} did not open a fixture page"
        )

    def _open_football_hub(self, browser: Any, competition_labels: tuple[str, ...]) -> None:
        football_xpath = _exact_text_xpath("Football")
        competition_xpath = " | ".join(_exact_text_xpath(label) for label in competition_labels)
        menu_xpath = _exact_text_xpath("Competitions")
        self._navigate(browser, self._homepage_url)
        self._dismiss_cookie_consent(browser)
        browser.wait_for_xpath(football_xpath, timeout=self._timeout_seconds)
        candidate_count = browser.count_xpath(football_xpath)

        # Hydration can add navigation links after the first visible Football label.
        for candidate_attempt in range(max(candidate_count, 4)):
            if candidate_attempt:
                self._navigate(browser, self._homepage_url)
                browser.wait_for_xpath(football_xpath, timeout=self._timeout_seconds)
            current_candidate_count = browser.count_xpath(football_xpath)
            if current_candidate_count == 0:
                continue
            candidate_index = min(candidate_attempt, current_candidate_count - 1)
            starting_url = browser.get_current_url()
            self._throttle()
            try:
                browser.click_xpath(football_xpath, index=candidate_index)
                browser.wait_for_url_change(starting_url, timeout=self._timeout_seconds)
                browser.wait_for_xpath(
                    competition_xpath + " | " + menu_xpath, timeout=self._timeout_seconds
                )
                if not browser.count_xpath(competition_xpath) and browser.count_xpath(menu_xpath):
                    self._throttle()
                    browser.click_xpath(menu_xpath)
                    browser.wait_for_xpath(competition_xpath, timeout=self._timeout_seconds)
            except (LookupError, TimeoutError) as exc:
                LOGGER.debug(
                    "Bet365 Football candidate %s of %s did not open the hub: %s",
                    candidate_index + 1,
                    current_candidate_count,
                    exc,
                )
                continue
            browser.sleep(self._browser_idle_seconds)
            return

        raise Bet365IngestionError("Bet365 Football navigation did not open its competition hub")

    def _dismiss_cookie_consent(self, browser: Any) -> None:
        try:
            browser.wait_for_xpath(
                _COOKIE_ACCEPT_XPATH,
                timeout=min(self._timeout_seconds, 3.0),
            )
        except TimeoutError:
            return

        for _ in range(2):
            try:
                browser.click_xpath(_COOKIE_ACCEPT_XPATH)
            except LookupError:
                return
            browser.sleep(max(self._browser_idle_seconds, 0.3))
            if browser.count_xpath(_COOKIE_ACCEPT_XPATH) == 0:
                return

        LOGGER.warning("Bet365 cookie consent remained visible after accepting it")

    def _try_open_competition_from_current_page(
        self,
        browser: Any,
        competition_labels: tuple[str, ...],
    ) -> tuple[str, list[Bet365FixtureListing]] | None:
        origin_url = browser.get_current_url()
        for label in competition_labels:
            if browser.get_current_url() != origin_url:
                self._navigate(browser, origin_url)
            label_xpath = _exact_text_xpath(label)
            candidate_count = browser.count_xpath(label_xpath)
            for candidate_attempt in range(candidate_count):
                if candidate_attempt or browser.get_current_url() != origin_url:
                    self._navigate(browser, origin_url)
                current_candidate_count = browser.count_xpath(label_xpath)
                if current_candidate_count == 0:
                    continue
                candidate_index = min(candidate_attempt, current_candidate_count - 1)
                starting_url = browser.get_current_url()
                self._throttle()
                try:
                    browser.click_xpath(label_xpath, index=candidate_index)
                    browser.wait_for_url_change(starting_url, timeout=self._timeout_seconds)
                    browser.wait_for_xpath(
                        _exact_text_xpath(_MARKET_TITLE),
                        timeout=self._timeout_seconds,
                    )
                except (LookupError, TimeoutError) as exc:
                    LOGGER.debug(
                        "Bet365 competition candidate %s of %s for %r did not open: %s",
                        candidate_index + 1,
                        current_candidate_count,
                        label,
                        exc,
                    )
                    continue
                browser.sleep(self._browser_idle_seconds)
                listings = parse_competition_fixture_listings(
                    browser.get_page_source(),
                    reference_time=self._utc_clock(),
                )
                cutoff = self._utc_clock() + self._pre_match_cutoff
                eligible = [
                    listing
                    for listing in listings
                    if listing.kickoff_at is not None and listing.kickoff_at > cutoff
                ]
                if not eligible:
                    LOGGER.info(
                        "Bet365 competition page contained no fixtures beyond the pre-match cutoff"
                    )
                return browser.get_current_url(), eligible
        return None

    def _open_fixture(
        self,
        browser: Any,
        competition_url: str,
        listing: Bet365FixtureListing,
    ) -> tuple[Bet365DiscoveredFixture, str]:
        row_xpath = _fixture_row_xpath(listing.home_team, listing.away_team)
        self._navigate(browser, competition_url)
        browser.wait_for_xpath(row_xpath, timeout=self._timeout_seconds)
        starting_url = browser.get_current_url()
        self._throttle()
        browser.click_xpath(row_xpath)
        browser.wait_for_url_change(starting_url, timeout=self._timeout_seconds)
        match_url = browser.get_current_url()
        provider_event_id = provider_event_id_from_url(match_url)
        if provider_event_id is None:
            raise Bet365IngestionError(
                f"Bet365 fixture click did not produce a match event URL: {match_url}"
            )
        browser.wait_for_xpath(_exact_text_xpath(_MARKET_TITLE), timeout=self._timeout_seconds)
        browser.sleep(self._browser_idle_seconds)
        return (
            Bet365DiscoveredFixture(
                provider_event_id=provider_event_id,
                home_team=listing.home_team,
                away_team=listing.away_team,
                date_label=listing.date_label,
                kickoff_time_label=listing.kickoff_time_label,
                kickoff_at=listing.kickoff_at,
                source_url=match_url,
            ),
            browser.get_page_source(),
        )

    def _open_event_url(
        self,
        browser: Any,
        fixture: Bet365DiscoveredFixture,
    ) -> str:
        self._navigate(browser, fixture.source_url)
        current_url = browser.get_current_url()
        current_event_id = provider_event_id_from_url(current_url)
        if current_event_id != fixture.provider_event_id:
            raise Bet365IngestionError(
                "Bet365 event URL did not remain on the expected event "
                f"{fixture.provider_event_id}: {current_url}"
            )
        return browser.get_page_source()

    def _navigate(self, browser: Any, url: str) -> None:
        self._throttle()
        browser.open(url)
        browser.sleep(self._browser_idle_seconds)

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_navigation_at is not None:
            wait = self._request_interval_seconds - (now - self._last_navigation_at)
            if wait > 0:
                self._sleeper(wait)
                now = self._clock()
        self._last_navigation_at = now

    def _assert_enabled(self) -> None:
        if not self._browser_enabled:
            raise Bet365SourceDisabledError(
                "Bet365 website ingestion requires STOCKBALL_BET365_BROWSER_ENABLED=true"
            )
