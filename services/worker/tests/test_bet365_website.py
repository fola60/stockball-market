from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

from app.ingestion.betting_markets import (
    MATCH_RESULT_1X2,
    Bet365Client,
    Bet365DiscoveredFixture,
    Bet365SourceDisabledError,
    decimal_odds_from_display,
    parse_competition_fixture_listings,
    parse_saved_page_url,
    parse_website_match_1x2,
    parse_website_player_markets,
    provider_event_id_from_url,
)


HOME_URL = "https://www.bet365.com/#/HO/"
FOOTBALL_HUB_URL = "https://www.bet365.com/#/AS/B1/K%5E5/"
COMPETITION_URL = "https://www.bet365.com/#/AC/B1/C1/D1002/E91422157/G40/"
MATCH_URL = "https://www.bet365.com/#/AC/B1/C1/D8/E196564288/F3/I1/"

HOME_HTML = """
<!doctype html><html><body><span>Premier League</span></body></html>
"""
COMPETITION_HTML = """
<!doctype html><html><body>
  <h3>Full Time Result</h3>
  <div>Sat 29 Aug</div>
  <article>
    <section><time>15:00</time><div>Bournemouth</div><div>Everton</div><div>8</div></section>
    <span>6/5</span><span>5/2</span><span>9/4</span>
  </div>
</body></html>
"""
CURRENT_COMPETITION_HTML = """
<!doctype html><html><body>
  <div>Full Time Result</div>
  <header class="unrelated-date-style">Fri 04 Sep</header>
  <section class="unrelated-row-style">
    <div class="unrelated-navigation-style">
      <div>20:00</div><div>Ipswich</div><div>Liverpool</div>
    </div>
    <span class="unrelated-odds-style">17/4</span>
    <span class="unrelated-odds-style">15/4</span>
    <span class="unrelated-odds-style">1/2</span>
  </section>
</body></html>
"""
MATCH_HTML = f"""
<!doctype html>
<!-- saved from url=(0054){MATCH_URL} -->
<html><body>
  <section class="arbitrary-market-style">
    <h2>Full Time Result</h2><span>BB</span><span>EARLY PAYOUT</span>
    <div class="arbitrary-selection-style">
      <span>Bournemouth</span><span>6/5</span>
    </div>
    <div><span>Draw</span><span>5/2</span></div>
    <div><span>Everton</span><span>9/4</span></div>
  </section>
</body></html>
"""
PLAYER_MARKETS_HTML = f"""
<!doctype html>
<!-- saved from url=(0054){MATCH_URL} -->
<html><body>
  <section class="arbitrary-grid">
    <h2>Shots On Target</h2><span>BB</span><span>Sub On Play On</span>
    <div>Player / Last 5</div>
    <div>9</div><div>Evanilson</div><div>0</div>
    <div>11</div><div>Thierno Barry</div><div>1</div>
    <span>1+</span><span>4/11</span><span>4/9</span>
    <span>2+</span><span>13/8</span><span>9/4</span>
  </section>
  <section>
    <h2>Score or Assist</h2><span>BB</span>
    <div>Starting Players</div>
    <div>9</div><div>Evanilson</div><div>0</div>
    <div>11</div><div>Thierno Barry</div><div>1</div>
    <span>Score</span><span>6/4</span><span>9/4</span>
    <span>Assist</span><span>8/1</span><span>9/1</span>
    <span>Score or Assist</span><span>6/5</span><span>7/4</span>
  </section>
  <section><h2>Cards</h2><span>BB</span></section>
</body></html>
"""

HOME_WITH_FOOTBALL_HTML = """
<!doctype html><html><body><span>Football</span></body></html>
"""
FOOTBALL_HUB_HTML = """
<!doctype html><html><body><div class="snm-2">England Premier League</div></body></html>
"""


class FakeBrowser:
    def __init__(self) -> None:
        self.current_url = HOME_URL
        self.opened: list[str] = []

    def open(self, url: str) -> None:
        self.current_url = url
        self.opened.append(url)

    def sleep(self, seconds: float) -> None:
        pass

    def get_page_source(self) -> str:
        if self.current_url == HOME_URL:
            return HOME_HTML
        if self.current_url == COMPETITION_URL:
            return COMPETITION_HTML
        if self.current_url == MATCH_URL:
            return MATCH_HTML
        raise AssertionError(f"unexpected fake browser URL: {self.current_url}")

    def get_current_url(self) -> str:
        return self.current_url

    def count_xpath(self, xpath: str) -> int:
        return 1 if self.current_url == HOME_URL and "Premier League" in xpath else 0

    def click_xpath(self, xpath: str, index: int = 0) -> None:
        if self.current_url == HOME_URL and "Premier League" in xpath:
            self.current_url = COMPETITION_URL
            return
        if self.current_url == COMPETITION_URL and "Bournemouth" in xpath and "Everton" in xpath:
            self.current_url = MATCH_URL
            return
        raise LookupError(f"fake browser cannot click XPath: {xpath}")

    def wait_for_xpath(self, xpath: str, timeout: float = 15.0) -> None:
        if self.current_url == HOME_URL and "Premier League" in xpath:
            return
        if self.current_url == COMPETITION_URL and (
            "Full Time Result" in xpath
            or ("Bournemouth" in xpath and "BournemouthEverton" in xpath)
        ):
            return
        if self.current_url == MATCH_URL and "Full Time Result" in xpath:
            return
        raise TimeoutError(f"fake browser XPath unavailable: {xpath}")

    def wait_for_url_change(self, previous_url: str, timeout: float = 15.0) -> None:
        if self.current_url == previous_url:
            raise TimeoutError(f"fake browser URL did not change from {previous_url}")


class FootballHubBrowser(FakeBrowser):
    def get_page_source(self) -> str:
        if self.current_url == HOME_URL:
            return HOME_WITH_FOOTBALL_HTML
        if self.current_url == FOOTBALL_HUB_URL:
            return FOOTBALL_HUB_HTML
        return super().get_page_source()

    def count_xpath(self, xpath: str) -> int:
        if self.current_url == HOME_URL:
            return 1 if "normalize-space(text())='Football'" in xpath else 0
        if self.current_url == FOOTBALL_HUB_URL:
            return 1 if "England Premier League" in xpath else 0
        return super().count_xpath(xpath)

    def click_xpath(self, xpath: str, index: int = 0) -> None:
        if self.current_url == HOME_URL and "normalize-space(text())='Football'" in xpath:
            self.current_url = FOOTBALL_HUB_URL
            return
        if self.current_url == FOOTBALL_HUB_URL and "England Premier League" in xpath:
            self.current_url = COMPETITION_URL
            return
        super().click_xpath(xpath, index=index)

    def wait_for_xpath(self, xpath: str, timeout: float = 15.0) -> None:
        if self.current_url == HOME_URL and "normalize-space(text())='Football'" in xpath:
            return
        if self.current_url == FOOTBALL_HUB_URL and "England Premier League" in xpath:
            return
        super().wait_for_xpath(xpath, timeout=timeout)


@contextmanager
def browser_context(browser: FakeBrowser):
    yield browser


class Bet365WebsiteParserTests(unittest.TestCase):
    def test_parses_competition_fixture_rows(self) -> None:
        fixtures = parse_competition_fixture_listings(
            COMPETITION_HTML,
            reference_time=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0].home_team, "Bournemouth")
        self.assertEqual(fixtures[0].away_team, "Everton")
        self.assertEqual(fixtures[0].date_label, "Sat 29 Aug")
        self.assertEqual(fixtures[0].kickoff_at, datetime(2026, 8, 29, 14, 0, tzinfo=UTC))
        self.assertEqual(fixtures[0].fractional_odds, ("6/5", "5/2", "9/4"))

    def test_parses_current_competition_fixture_structure(self) -> None:
        fixtures = parse_competition_fixture_listings(
            CURRENT_COMPETITION_HTML,
            reference_time=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0].home_team, "Ipswich")
        self.assertEqual(fixtures[0].away_team, "Liverpool")
        self.assertEqual(fixtures[0].kickoff_at, datetime(2026, 9, 4, 19, 0, tzinfo=UTC))
        self.assertEqual(fixtures[0].fractional_odds, ("17/4", "15/4", "1/2"))

    def test_parses_exact_full_time_result_market(self) -> None:
        observed_at = datetime(2026, 8, 29, 14, 45, tzinfo=UTC)
        observations = parse_website_match_1x2(MATCH_HTML, observed_at=observed_at)

        self.assertEqual([item.selection_key for item in observations], ["HOME", "DRAW", "AWAY"])
        self.assertEqual(
            [item.decimal_odds for item in observations],
            [Decimal("2.2"), Decimal("3.5"), Decimal("3.25")],
        )
        self.assertTrue(all(item.provider_event_id == "196564288" for item in observations))
        self.assertTrue(all(item.market_key == MATCH_RESULT_1X2 for item in observations))
        self.assertEqual(observations[0].raw_payload["home_team"], "Bournemouth")
        self.assertEqual(observations[0].observed_at, observed_at)

    def test_parses_expanded_player_threshold_and_score_assist_markets(self) -> None:
        observed_at = datetime(2026, 8, 29, 14, 45, tzinfo=UTC)

        observations = parse_website_player_markets(
            PLAYER_MARKETS_HTML,
            observed_at=observed_at,
        )

        self.assertEqual(len(observations), 10)
        by_type: dict[str, list] = {}
        for observation in observations:
            by_type.setdefault(observation.selection.market_type, []).append(observation)
        self.assertEqual(len(by_type["SHOTS_ON_TARGET"]), 4)
        self.assertEqual(len(by_type["GOALSCORER"]), 2)
        self.assertEqual(len(by_type["ASSIST"]), 2)
        self.assertEqual(len(by_type["SCORE_OR_ASSIST"]), 2)
        shot = by_type["SHOTS_ON_TARGET"][0]
        self.assertEqual(shot.selection.line, Decimal("1"))
        self.assertEqual(shot.selection.outcome_type.value, "AT_LEAST")
        self.assertEqual(
            shot.selection.participants[0].provider_player_name,
            "Evanilson",
        )
        self.assertEqual(
            shot.selection.canonical_selection_key,
            "SHOTS_ON_TARGET|FULL_MATCH|AT_LEAST|1|evanilson",
        )
        self.assertEqual(shot.observed_at, observed_at)

    def test_skips_collapsed_player_market_without_complete_odds_grid(self) -> None:
        observations = parse_website_player_markets(
            f"<!-- saved from url=(0054){MATCH_URL} --><h2>Cards</h2><span>BB</span>"
        )

        self.assertEqual(observations, [])

    def test_reads_saved_page_url_and_event_id(self) -> None:
        self.assertEqual(parse_saved_page_url(MATCH_HTML), MATCH_URL)
        self.assertEqual(provider_event_id_from_url(MATCH_URL), "196564288")

    def test_converts_fractional_evens_and_decimal_odds(self) -> None:
        self.assertEqual(decimal_odds_from_display("6/5"), Decimal("2.2"))
        self.assertEqual(decimal_odds_from_display("EVS"), Decimal("2"))
        self.assertEqual(decimal_odds_from_display("2.35"), Decimal("2.35"))
        self.assertIsNone(decimal_odds_from_display("SP"))


class Bet365ClientTests(unittest.TestCase):
    def test_discovers_competition_and_match_then_parses_market(self) -> None:
        browser = FakeBrowser()
        client = Bet365Client(
            browser_enabled=True,
            request_interval_seconds=0,
            browser_idle_seconds=0,
            browser_factory=lambda: browser_context(browser),
            utc_clock=lambda: datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        )

        observations = client.list_pre_match_1x2("PL")

        self.assertEqual(len(observations), 3)
        self.assertEqual(browser.opened, [HOME_URL, COMPETITION_URL])
        self.assertEqual(observations[2].source_url, MATCH_URL)
        self.assertEqual(
            observations[0].selection.raw_payload["kickoff_at"],
            "2026-08-29T14:00:00+00:00",
        )

    def test_refreshes_known_live_event_url_without_competition_discovery(self) -> None:
        browser = FakeBrowser()
        client = Bet365Client(
            browser_enabled=True,
            request_interval_seconds=0,
            browser_idle_seconds=0,
            browser_factory=lambda: browser_context(browser),
            utc_clock=lambda: datetime(2026, 8, 29, 14, 30, tzinfo=UTC),
        )
        fixture = Bet365DiscoveredFixture(
            provider_event_id="196564288",
            home_team="Bournemouth",
            away_team="Everton",
            date_label="Sat 29 Aug",
            kickoff_time_label="15:00",
            kickoff_at=datetime(2026, 8, 29, 14, 0, tzinfo=UTC),
            source_url=MATCH_URL,
        )

        observations = client.list_live_markets((fixture,))

        self.assertEqual(len(observations), 3)
        self.assertEqual(browser.opened, [MATCH_URL])
        self.assertEqual(observations[0].observed_at, datetime(2026, 8, 29, 14, 30, tzinfo=UTC))

    def test_discovers_competition_through_football_hub(self) -> None:
        browser = FootballHubBrowser()
        client = Bet365Client(
            browser_enabled=True,
            request_interval_seconds=0,
            browser_idle_seconds=0,
            browser_factory=lambda: browser_context(browser),
            utc_clock=lambda: datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        )

        observations = client.list_pre_match_1x2("PL")

        self.assertEqual(len(observations), 3)
        self.assertEqual(browser.opened, [HOME_URL, COMPETITION_URL])

    def test_skips_fixture_inside_pre_match_cutoff(self) -> None:
        browser = FakeBrowser()
        client = Bet365Client(
            browser_enabled=True,
            request_interval_seconds=0,
            browser_idle_seconds=0,
            browser_factory=lambda: browser_context(browser),
            utc_clock=lambda: datetime(2026, 8, 29, 13, 58, tzinfo=UTC),
        )

        discovery = client.discover_pre_match_pages("PL")

        self.assertEqual(discovery.fixtures, ())
        self.assertEqual(browser.opened, [HOME_URL])

    def test_client_requires_browser_to_be_enabled(self) -> None:
        client = Bet365Client(
            browser_enabled=False,
            request_interval_seconds=0,
            browser_factory=lambda: browser_context(FakeBrowser()),
        )

        with self.assertRaises(Bet365SourceDisabledError):
            client.list_pre_match_1x2("PL")


if __name__ == "__main__":
    unittest.main()
