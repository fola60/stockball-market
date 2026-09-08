from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from .errors import Bet365IngestionError
from .models import (
    BET365_PROVIDER,
    MATCH_RESULT_1X2,
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

_SAVED_PAGE_URL_PATTERN = re.compile(
    r"<!--\s*saved from url=\(\d+\)(?P<url>.*?)\s*-->",
    re.IGNORECASE | re.DOTALL,
)
_EVENT_ID_PATTERN = re.compile(r"(?:^|/)D8/E(?P<event_id>\d+)(?:/|$)", re.IGNORECASE)
_FIXTURE_DATE_PATTERN = re.compile(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} [A-Z][a-z]{2}$")
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
