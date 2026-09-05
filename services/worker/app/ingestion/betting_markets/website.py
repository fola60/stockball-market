from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from app.ingestion.fetch import ContentFetchService, FetchResponseError, FetchUnavailableError

from .errors import Bet365IngestionError, Bet365SourceDisabledError
from .models import (
    BET365_PROVIDER,
    MATCH_RESULT_1X2,
    Bet365CompetitionDiscovery,
    Bet365DiscoveredFixture,
    Bet365FixtureListing,
    BettingMarketObservation,
    BettingMarketParticipant,
    BettingMarketSelection,
    MarketOutcomeType,
    MarketPeriod,
    MarketScope,
    PlayerMarketType,
)


LOGGER = logging.getLogger(__name__)

DEFAULT_BET365_HOMEPAGE_URL = "https://www.bet365.com/#/HO/"
DEFAULT_BET365_COMPETITION_NAME = "Premier League"

_SAVED_PAGE_URL_PATTERN = re.compile(
    r"<!--\s*saved from url=\(\d+\)(?P<url>.*?)\s*-->",
    re.IGNORECASE | re.DOTALL,
)
_EVENT_ID_PATTERN = re.compile(r"(?:^|/)D8/E(?P<event_id>\d+)(?:/|$)", re.IGNORECASE)
_FIXTURE_DATE_PATTERN = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2}$"
)
_FIXTURE_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_MARKET_TITLE = "Full Time Result"
_THRESHOLD_PATTERN = re.compile(r"^(?P<line>\d+(?:\.\d+)?)\+$")
_PLAYER_GRID_MARKETS = {
    "Shots": PlayerMarketType.SHOTS,
    "Shots On Target": PlayerMarketType.SHOTS_ON_TARGET,
    "Cards": PlayerMarketType.CARD,
    "Fouls Committed": PlayerMarketType.FOULS_COMMITTED,
    "To Be Fouled": PlayerMarketType.FOULS_DRAWN,
}
_SCORE_OR_ASSIST_COLUMNS = {
    "Score": PlayerMarketType.GOALSCORER,
    "Assist": PlayerMarketType.ASSIST,
    "Score or Assist": PlayerMarketType.SCORE_OR_ASSIST,
}


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
        utc_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
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
            raise Bet365IngestionError("Bet365 website browser session failed") from exc

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
            raise Bet365IngestionError("Bet365 website browser session failed") from exc

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
        competition_xpath = " | ".join(
            _exact_text_xpath(label) for label in competition_labels
        )
        self._navigate(browser, self._homepage_url)
        browser.wait_for_xpath(football_xpath, timeout=self._timeout_seconds)
        candidate_count = browser.count_xpath(football_xpath)

        for candidate_index in range(candidate_count):
            if candidate_index:
                self._navigate(browser, self._homepage_url)
                browser.wait_for_xpath(football_xpath, timeout=self._timeout_seconds)
            starting_url = browser.get_current_url()
            self._throttle()
            browser.click_xpath(football_xpath, index=candidate_index)
            try:
                browser.wait_for_url_change(starting_url, timeout=self._timeout_seconds)
                browser.wait_for_xpath(competition_xpath, timeout=self._timeout_seconds)
            except (LookupError, TimeoutError):
                continue
            browser.sleep(self._browser_idle_seconds)
            return

        raise Bet365IngestionError("Bet365 Football navigation did not open its competition hub")

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
            for candidate_index in range(candidate_count):
                if candidate_index or browser.get_current_url() != origin_url:
                    self._navigate(browser, origin_url)
                starting_url = browser.get_current_url()
                self._throttle()
                browser.click_xpath(label_xpath, index=candidate_index)
                try:
                    browser.wait_for_url_change(starting_url, timeout=self._timeout_seconds)
                    browser.wait_for_xpath(
                        _exact_text_xpath(_MARKET_TITLE),
                        timeout=self._timeout_seconds,
                    )
                except (LookupError, TimeoutError):
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
                        "Bet365 competition page contained no fixtures beyond "
                        "the pre-match cutoff"
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


def parse_saved_page_url(html: str) -> str | None:
    match = _SAVED_PAGE_URL_PATTERN.search(html[:2048])
    if match is None:
        return None
    url = unescape(match.group("url")).strip()
    return url or None


def parse_competition_fixture_listings(
    html: str,
    *,
    reference_time: datetime | None = None,
) -> list[Bet365FixtureListing]:
    soup = BeautifulSoup(html, "html.parser")
    listings: list[Bet365FixtureListing] = []
    seen: set[tuple[str | None, str, str, str]] = set()
    for time_text in soup.find_all(string=_matches_fixture_time):
        time_node = time_text.parent
        if not isinstance(time_node, Tag):
            continue
        parsed_row = _parse_fixture_ancestor(time_node)
        if parsed_row is None:
            continue
        row, team_names, odds = parsed_row
        date_label = _nearest_fixture_date(row)
        kickoff_time_label = _normalized_text(str(time_text))
        fixture_key = (date_label, kickoff_time_label, team_names[0], team_names[1])
        if fixture_key in seen:
            continue
        seen.add(fixture_key)
        listings.append(
            Bet365FixtureListing(
                home_team=team_names[0],
                away_team=team_names[1],
                date_label=date_label,
                kickoff_time_label=kickoff_time_label,
                kickoff_at=_parse_fixture_kickoff(
                    date_label, kickoff_time_label,
                    reference_time=reference_time,
                ),
                fractional_odds=(odds[0], odds[1], odds[2]),
            )
        )
    if not listings:
        raise Bet365IngestionError("Bet365 competition page did not contain fixture rows")
    return listings


def parse_website_match_1x2(
    html: str,
    *,
    source_url: str | None = None,
    observed_at: datetime | None = None,
    expected_home_team: str | None = None,
    expected_away_team: str | None = None,
) -> list[BettingMarketObservation]:
    resolved_url = source_url or parse_saved_page_url(html)
    provider_event_id = provider_event_id_from_url(resolved_url)
    if provider_event_id is None:
        raise Bet365IngestionError("Bet365 match page URL did not contain a D8 event ID")

    soup = BeautifulSoup(html, "html.parser")
    market_titles = [
        text.parent
        for text in soup.find_all(string=lambda value: _normalized_text(value) == _MARKET_TITLE)
        if isinstance(text.parent, Tag)
    ]
    if not market_titles:
        raise Bet365IngestionError("Bet365 match page did not contain Full Time Result")
    selections = _find_full_time_result_selections(
        market_titles,
        expected_home_team=expected_home_team,
        expected_away_team=expected_away_team,
    )
    if selections is None:
        raise Bet365IngestionError("Bet365 Full Time Result did not contain home/draw/away")

    home_team, away_team = selections[0][0], selections[2][0]
    if expected_home_team and _team_key(home_team) != _team_key(expected_home_team):
        raise Bet365IngestionError(
            f"Bet365 match page home team {home_team!r} did not match {expected_home_team!r}"
        )
    if expected_away_team and _team_key(away_team) != _team_key(expected_away_team):
        raise Bet365IngestionError(
            f"Bet365 match page away team {away_team!r} did not match {expected_away_team!r}"
        )

    timestamp = observed_at or datetime.now(UTC)
    outcome_types = (
        MarketOutcomeType.HOME,
        MarketOutcomeType.DRAW,
        MarketOutcomeType.AWAY,
    )
    return [
        BettingMarketObservation(
            selection=BettingMarketSelection(
                provider=BET365_PROVIDER,
                provider_event_id=provider_event_id,
                fixture_provider_id=None,
                market_scope=MarketScope.MATCH,
                market_type=MATCH_RESULT_1X2,
                period=MarketPeriod.FULL_MATCH,
                outcome_type=outcome_type,
                line=None,
                canonical_selection_key=_canonical_selection_key(
                    MATCH_RESULT_1X2,
                    MarketPeriod.FULL_MATCH,
                    outcome_type,
                    None,
                    (),
                ),
                provider_market_label=_MARKET_TITLE,
                provider_selection_label=selection_name,
                participants=(),
                raw_payload={
                    "home_team": home_team,
                    "away_team": away_team,
                },
            ),
            decimal_odds=decimal_odds,
            implied_probability=Decimal("1") / decimal_odds,
            observed_at=timestamp,
            source_url=resolved_url,
            raw_payload={
                "source": "website",
                "home_team": home_team,
                "away_team": away_team,
                "market": "Full Time Result",
                "selection": selection_name,
                "display_odds": display_odds,
            },
        )
        for outcome_type, (selection_name, display_odds, decimal_odds) in zip(
            outcome_types,
            selections,
            strict=True,
        )
    ]


def parse_website_player_markets(
    html: str,
    *,
    source_url: str | None = None,
    observed_at: datetime | None = None,
) -> list[BettingMarketObservation]:
    resolved_url = source_url or parse_saved_page_url(html)
    provider_event_id = provider_event_id_from_url(resolved_url)
    if provider_event_id is None:
        raise Bet365IngestionError("Bet365 match page URL did not contain a D8 event ID")

    soup = BeautifulSoup(html, "html.parser")
    timestamp = observed_at or datetime.now(UTC)
    observations: list[BettingMarketObservation] = []
    for provider_label, market_type in _PLAYER_GRID_MARKETS.items():
        observations.extend(
            _parse_threshold_player_market(
                soup,
                provider_event_id=provider_event_id,
                provider_label=provider_label,
                market_type=market_type,
                observed_at=timestamp,
                source_url=resolved_url,
            )
        )
    observations.extend(
        _parse_score_or_assist_market(
            soup,
            provider_event_id=provider_event_id,
            observed_at=timestamp,
            source_url=resolved_url,
        )
    )

    deduplicated: dict[str, BettingMarketObservation] = {}
    for observation in observations:
        deduplicated.setdefault(
            observation.selection.canonical_selection_key,
            observation,
        )
    return list(deduplicated.values())


def _parse_threshold_player_market(
    soup: BeautifulSoup,
    *,
    provider_event_id: str,
    provider_label: str,
    market_type: PlayerMarketType,
    observed_at: datetime,
    source_url: str | None,
) -> list[BettingMarketObservation]:
    for tokens in _semantic_market_token_sets(soup, provider_label):
        parsed = _parse_player_grid(tokens, _threshold_column)
        if parsed is None:
            continue
        players, columns = parsed
        return [
            _player_market_observation(
                provider_event_id=provider_event_id,
                provider_market_label=provider_label,
                provider_player_name=player,
                market_type=market_type,
                outcome_type=MarketOutcomeType.AT_LEAST,
                line=line,
                displayed_odds=displayed_odds,
                observed_at=observed_at,
                source_url=source_url,
            )
            for line, odds in columns
            for player, displayed_odds in zip(players, odds, strict=True)
        ]
    return []


def _parse_score_or_assist_market(
    soup: BeautifulSoup,
    *,
    provider_event_id: str,
    observed_at: datetime,
    source_url: str | None,
) -> list[BettingMarketObservation]:
    provider_label = "Score or Assist"
    for tokens in _semantic_market_token_sets(soup, provider_label):
        parsed = _parse_player_grid(tokens, _score_or_assist_column)
        if parsed is None:
            continue
        players, columns = parsed
        return [
            _player_market_observation(
                provider_event_id=provider_event_id,
                provider_market_label=provider_label,
                provider_player_name=player,
                market_type=market_type,
                outcome_type=MarketOutcomeType.ANYTIME,
                line=Decimal("1"),
                displayed_odds=displayed_odds,
                observed_at=observed_at,
                source_url=source_url,
            )
            for market_type, odds in columns
            for player, displayed_odds in zip(players, odds, strict=True)
        ]
    return []


def _semantic_market_token_sets(
    soup: BeautifulSoup,
    provider_label: str,
) -> list[list[str]]:
    title_nodes = [
        text.parent
        for text in soup.find_all(
            string=lambda value: _normalized_text(value) == provider_label
        )
        if isinstance(text.parent, Tag)
    ]
    token_sets: list[list[str]] = []
    for title in title_nodes:
        for ancestor in title.parents:
            if not isinstance(ancestor, Tag) or ancestor.name in {"body", "html"}:
                break
            tokens = [_normalized_text(value) for value in ancestor.stripped_strings]
            if tokens and tokens[0] == provider_label:
                token_sets.append(tokens)
    return token_sets


def _parse_player_grid(
    tokens: list[str],
    parse_column: Callable[[str], Any | None],
) -> tuple[list[str], list[tuple[object, list[str]]]] | None:
    player_header_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if token in {"Player / Last 5", "Starting Players"}
        ),
        None,
    )
    if player_header_index is None:
        return None
    first_column_index = next(
        (
            index
            for index in range(player_header_index + 1, len(tokens))
            if parse_column(tokens[index]) is not None
        ),
        None,
    )
    if first_column_index is None:
        return None

    players = [
        token
        for token in tokens[player_header_index + 1 : first_column_index]
        if _is_player_name_token(token)
    ]
    if not players:
        return None

    columns: list[tuple[object, list[str]]] = []
    index = first_column_index
    while index < len(tokens):
        column = parse_column(tokens[index])
        if column is None:
            break
        index += 1
        odds: list[str] = []
        while index < len(tokens) and decimal_odds_from_display(tokens[index]) is not None:
            odds.append(tokens[index])
            index += 1
        if len(odds) != len(players):
            break
        columns.append((column, odds))
    return (players, columns) if columns else None


def _threshold_column(value: str) -> Decimal | None:
    match = _THRESHOLD_PATTERN.fullmatch(value)
    return Decimal(match.group("line")) if match else None


def _score_or_assist_column(value: str) -> PlayerMarketType | None:
    return _SCORE_OR_ASSIST_COLUMNS.get(value)


def _is_player_name_token(value: str) -> bool:
    return bool(
        value
        and value.casefold() not in {"n/a", "show more", "others on request"}
        and not value.isdecimal()
        and decimal_odds_from_display(value) is None
        and _THRESHOLD_PATTERN.fullmatch(value) is None
    )


def _player_market_observation(
    *,
    provider_event_id: str,
    provider_market_label: str,
    provider_player_name: str,
    market_type: PlayerMarketType,
    outcome_type: MarketOutcomeType,
    line: Decimal,
    displayed_odds: str,
    observed_at: datetime,
    source_url: str | None,
) -> BettingMarketObservation:
    decimal_odds = decimal_odds_from_display(displayed_odds)
    if decimal_odds is None:
        raise ValueError(f"invalid Bet365 player odds: {displayed_odds}")
    participants = (BettingMarketParticipant(provider_player_name),)
    provider_selection_label = (
        f"{provider_player_name} {outcome_type.value} {line.normalize()}"
    )
    return BettingMarketObservation(
        selection=BettingMarketSelection(
            provider=BET365_PROVIDER,
            provider_event_id=provider_event_id,
            fixture_provider_id=None,
            market_scope=MarketScope.PLAYER,
            market_type=market_type.value,
            period=MarketPeriod.FULL_MATCH,
            outcome_type=outcome_type,
            line=line,
            canonical_selection_key=_canonical_selection_key(
                market_type.value,
                MarketPeriod.FULL_MATCH,
                outcome_type,
                line,
                participants,
            ),
            provider_market_label=provider_market_label,
            provider_selection_label=provider_selection_label,
            participants=participants,
            raw_payload={"provider_player_name": provider_player_name},
        ),
        decimal_odds=decimal_odds,
        implied_probability=Decimal("1") / decimal_odds,
        observed_at=observed_at,
        source_url=source_url,
        raw_payload={
            "source": "website",
            "market": provider_market_label,
            "player": provider_player_name,
            "outcome": outcome_type.value,
            "line": str(line),
            "display_odds": displayed_odds,
        },
    )


def _canonical_selection_key(
    market_type: str,
    period: MarketPeriod,
    outcome_type: MarketOutcomeType,
    line: Decimal | None,
    participants: tuple[BettingMarketParticipant, ...],
) -> str:
    line_key = "-" if line is None else format(line.normalize(), "f")
    participant_key = "&".join(
        _key_component(participant.provider_player_name) for participant in participants
    ) or "-"
    return "|".join(
        (
            market_type,
            period.value,
            outcome_type.value,
            line_key,
            participant_key,
        )
    )


def _key_component(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _with_fixture_context(
    observation: BettingMarketObservation,
    fixture: Bet365DiscoveredFixture,
) -> BettingMarketObservation:
    fixture_context = {
        "home_team": fixture.home_team,
        "away_team": fixture.away_team,
        "date_label": fixture.date_label,
        "kickoff_time_label": fixture.kickoff_time_label,
        "kickoff_at": None if fixture.kickoff_at is None else fixture.kickoff_at.isoformat(),
    }
    selection = replace(
        observation.selection,
        raw_payload={**dict(observation.selection.raw_payload), **fixture_context},
    )
    return replace(
        observation,
        selection=selection,
        raw_payload={**dict(observation.raw_payload), **fixture_context},
    )


def provider_event_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = _EVENT_ID_PATTERN.search(urlparse(url).fragment)
    return match.group("event_id") if match else None


def decimal_odds_from_display(value: str | None) -> Decimal | None:
    normalized = (value or "").strip().upper()
    if normalized in {"EVS", "EVENS"}:
        return Decimal("2")
    if "/" in normalized:
        numerator_text, denominator_text = normalized.split("/", 1)
        try:
            numerator = Decimal(numerator_text)
            denominator = Decimal(denominator_text)
        except InvalidOperation:
            return None
        if numerator < 0 or denominator <= 0:
            return None
        return Decimal("1") + (numerator / denominator)
    try:
        decimal_odds = Decimal(normalized)
    except InvalidOperation:
        return None
    return decimal_odds if decimal_odds > Decimal("1") else None


def _competition_name(league: str | None, configured_name: str) -> str:
    if league is None:
        return configured_name
    normalized = league.strip()
    if normalized.upper() in {"PL", "EPL", "PREMIER_LEAGUE"}:
        return configured_name
    return _required_text(normalized, "league")


def _competition_navigation_labels(competition_name: str) -> tuple[str, ...]:
    if competition_name.casefold() == "premier league":
        return (competition_name, "England Premier League")
    return (competition_name,)


def _exact_text_xpath(text: str) -> str:
    return (
        "//*[self::span or self::div]"
        f"[normalize-space(text())={_xpath_literal(text)}]"
    )


def _fixture_row_xpath(home_team: str, away_team: str) -> str:
    home = _xpath_literal(home_team)
    combined_teams = _xpath_literal(f"{home_team}{away_team}")
    return (
        f"(//*[not(*) and normalize-space(.)={home}]"
        f"/ancestor::*[normalize-space(.)={combined_teams}][1])[1]"
    )


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"


def _matches_fixture_time(value: str | None) -> bool:
    return bool(value and _FIXTURE_TIME_PATTERN.fullmatch(_normalized_text(value)))


def _parse_fixture_ancestor(
    time_node: Tag,
) -> tuple[Tag, tuple[str, str], tuple[str, str, str]] | None:
    for ancestor in time_node.parents:
        if not isinstance(ancestor, Tag) or ancestor.name in {"body", "html"}:
            break
        odd_values = [
            text
            for span in ancestor.find_all("span")
            if (text := _node_text(span)) and decimal_odds_from_display(text) is not None
        ]
        if len(odd_values) != 3:
            continue
        tokens = [_normalized_text(value) for value in ancestor.stripped_strings]
        time_label = _node_text(time_node)
        if not time_label or time_label not in tokens:
            continue
        time_index = tokens.index(time_label)
        first_odds_index = next(
            (index for index, token in enumerate(tokens) if token == odd_values[0]),
            None,
        )
        if first_odds_index is None or first_odds_index <= time_index:
            continue
        team_names = tuple(
            token
            for token in tokens[time_index + 1 : first_odds_index]
            if _is_team_name_candidate(token)
        )
        if len(team_names) == 2:
            return ancestor, (team_names[0], team_names[1]), (
                odd_values[0],
                odd_values[1],
                odd_values[2],
            )
    return None


def _nearest_fixture_date(row: Tag) -> str | None:
    for value in row.find_all_previous(string=True):
        normalized = _normalized_text(value)
        if _FIXTURE_DATE_PATTERN.fullmatch(normalized):
            return normalized
    return None


def _is_team_name_candidate(value: str) -> bool:
    return bool(
        value
        and not value.isdecimal()
        and not _FIXTURE_TIME_PATTERN.fullmatch(value)
        and decimal_odds_from_display(value) is None
        and value.casefold() not in {"1", "x", "2"}
    )


def _find_full_time_result_selections(
    market_titles: list[Tag],
    *,
    expected_home_team: str | None,
    expected_away_team: str | None,
) -> list[tuple[str, str, Decimal]] | None:
    for title in market_titles:
        for ancestor in title.parents:
            if not isinstance(ancestor, Tag) or ancestor.name in {"body", "html"}:
                break
            pairs = _selection_pairs(
                [_normalized_text(value) for value in ancestor.stripped_strings]
            )
            for index, pair in enumerate(pairs):
                if pair[0].casefold() != "draw" or index == 0 or index + 1 >= len(pairs):
                    continue
                selections = [pairs[index - 1], pair, pairs[index + 1]]
                if expected_home_team and _team_key(selections[0][0]) != _team_key(
                    expected_home_team
                ):
                    continue
                if expected_away_team and _team_key(selections[2][0]) != _team_key(
                    expected_away_team
                ):
                    continue
                return selections
    return None


def _selection_pairs(tokens: list[str]) -> list[tuple[str, str, Decimal]]:
    pairs: list[tuple[str, str, Decimal]] = []
    for name, displayed_odds in zip(tokens, tokens[1:]):
        decimal_odds = decimal_odds_from_display(displayed_odds)
        if decimal_odds is not None and _is_selection_name(name):
            pairs.append((name, displayed_odds, decimal_odds))
    return pairs


def _is_selection_name(value: str) -> bool:
    return bool(
        value
        and decimal_odds_from_display(value) is None
        and not _FIXTURE_TIME_PATTERN.fullmatch(value)
        and value.casefold() not in {"full time result", "bb", "early payout", "acca boost"}
    )


def _normalized_text(value: object) -> str:
    return " ".join(str(value).split())


def _node_text(node: Tag | None) -> str | None:
    if node is None:
        return None
    normalized = " ".join(node.get_text(" ", strip=True).split())
    return normalized or None


def _team_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _parse_fixture_kickoff(
    date_label: str | None,
    time_label: str | None,
    *,
    reference_time: datetime | None,
) -> datetime | None:
    if not date_label or not time_label:
        return None
    reference = reference_time or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    london = ZoneInfo("Europe/London")
    local_reference = reference.astimezone(london)
    try:
        partial = datetime.strptime(f"{date_label} {time_label}", "%a %d %b %H:%M")
    except ValueError:
        return None
    candidates = [
        partial.replace(year=year, tzinfo=london)
        for year in (
            local_reference.year - 1,
            local_reference.year,
            local_reference.year + 1,
        )
    ]
    closest = min(candidates, key=lambda candidate: abs(candidate - local_reference))
    return closest.astimezone(UTC)


def _required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized
