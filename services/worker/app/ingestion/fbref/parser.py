from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from html.parser import HTMLParser
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from app.ingestion.fixtures.models import ExternalFixture
from app.ingestion.players.models import ExternalPlayer
from app.ingestion.stats.models import ExternalPlayerStat

from .models import (
    DEFAULT_FBREF_COMPETITION,
    DEFAULT_FBREF_COMPETITION_ID,
    FBREF_PROVIDER,
)


_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
_MATCH_ID_RE = re.compile(r"/matches/([^/]+)/")
_PLAYER_ID_RE = re.compile(r"/players/([^/]+)/")
_SQUAD_ID_RE = re.compile(r"/squads/([^/]+)(?:/|$)")
_TIME_RE = re.compile(r"\d{1,2}:\d{2}")
_NUMERIC_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
_INTEGER_RE = re.compile(r"[+-]?\d+")
_IDENTITY_STAT_KEYS = {
    "ranker",
    "player",
    "nationality",
    "position",
    "age",
    "team",
    "squad",
    "matches",
}


@dataclass(frozen=True)
class ParsedCell:
    data_stat: str | None
    text: str
    links: tuple[str, ...]


@dataclass(frozen=True)
class ParsedRow:
    values: Mapping[str, str]
    links: Mapping[str, tuple[str, ...]]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ParsedTable:
    table_id: str | None
    caption: str | None
    rows: tuple[ParsedRow, ...]


def parse_fixtures(
    html: str,
    *,
    source_url: str,
    season: int,
    competition_id: int = DEFAULT_FBREF_COMPETITION_ID,
    competition: str = DEFAULT_FBREF_COMPETITION,
    timezone_name: str = "Europe/London",
) -> list[ExternalFixture]:
    fixtures: list[ExternalFixture] = []
    for table in _fixture_tables(parse_tables(html)):
        for row in table.rows:
            if _is_header_row(row, "home_team", "home") or _is_empty_row(row):
                continue
            home_team_name = _value(row, "home_team", "home")
            away_team_name = _value(row, "away_team", "away")
            fixture_date = _value(row, "date")
            if not home_team_name or not away_team_name or not fixture_date:
                continue

            kickoff_at = _parse_kickoff(
                fixture_date,
                _value(row, "start_time", "time"),
                timezone_name,
            )
            home_team_url = _first_link(row, "home_team") or _first_link(row, "home")
            away_team_url = _first_link(row, "away_team") or _first_link(row, "away")
            home_team_provider_id = _extract_squad_id(home_team_url) or _slug(home_team_name)
            away_team_provider_id = _extract_squad_id(away_team_url) or _slug(away_team_name)
            match_report_url = _first_link(row, "match_report")
            provider_match_id = _extract_match_id(match_report_url)
            provider_fixture_id = _fixture_scope_id(
                competition_id,
                season,
                _value(row, "gameweek", "week"),
                home_team_provider_id,
                away_team_provider_id,
            )
            score = _value(row, "score")
            raw_payload = {
                "source_url": source_url,
                "match_url": _absolute_url(source_url, match_report_url),
                "provider_match_id": provider_match_id,
                "fbref_table_id": table.table_id,
                "fbref_raw_row": dict(row.raw),
            }
            fixtures.append(
                ExternalFixture(
                    provider=FBREF_PROVIDER,
                    provider_fixture_id=provider_fixture_id,
                    league_provider_id=str(competition_id),
                    season=season,
                    kickoff_at=kickoff_at,
                    home_team_provider_id=home_team_provider_id,
                    home_team_name=home_team_name,
                    away_team_provider_id=away_team_provider_id,
                    away_team_name=away_team_name,
                    status_short="FT" if score else "NS",
                    status_long="Finished" if score else "Not Started",
                    elapsed=None,
                    raw_payload=raw_payload,
                    competition=competition,
                    source_url=source_url,
                    provider_match_id=provider_match_id,
                )
            )
    return fixtures


def parse_players(
    html: str,
    *,
    source_url: str,
    season: int,
    competition: str = DEFAULT_FBREF_COMPETITION,
) -> list[ExternalPlayer]:
    players: list[ExternalPlayer] = []
    for table in _player_tables(parse_tables(html)):
        for row in table.rows:
            player_name = _value(row, "player")
            if not player_name or _is_header_row(row, "player"):
                continue
            player_url = _first_link(row, "player")
            provider_player_id = _extract_player_id(player_url)
            if provider_player_id is None:
                continue
            team_name = _value(row, "team", "squad")
            team_url = _first_link(row, "team") or _first_link(row, "squad")
            players.append(
                ExternalPlayer(
                    provider=FBREF_PROVIDER,
                    provider_player_id=provider_player_id,
                    display_name=player_name,
                    club=team_name,
                    position=_empty_to_none(_value(row, "position", "pos")),
                    metadata={
                        "provider_url": _absolute_url(source_url, player_url),
                        "provider_confidence": 1.0,
                        "source_url": source_url,
                        "season": season,
                        "competition": competition,
                        "team_provider_id": _extract_squad_id(team_url),
                        "team_url": _absolute_url(source_url, team_url),
                        "team_name": team_name,
                        "nationality": _empty_to_none(_value(row, "nationality", "nation")),
                        "age": _empty_to_none(_value(row, "age")),
                        "fbref_raw_row": dict(row.raw),
                    },
                )
            )
    return players


def parse_player_stats(
    html: str,
    *,
    source_url: str,
    season: int,
    stat_type: str,
    competition_id: int = DEFAULT_FBREF_COMPETITION_ID,
    competition: str = DEFAULT_FBREF_COMPETITION,
) -> list[ExternalPlayerStat]:
    observations: list[ExternalPlayerStat] = []
    for table in _player_tables(parse_tables(html)):
        for row in table.rows:
            player_name = _value(row, "player")
            if not player_name or _is_header_row(row, "player"):
                continue
            player_url = _first_link(row, "player")
            provider_player_id = _extract_player_id(player_url)
            if provider_player_id is None:
                continue
            team_name = _value(row, "team", "squad")
            team_url = _first_link(row, "team") or _first_link(row, "squad")
            team_provider_id = _extract_squad_id(team_url)
            provider_fixture_id = _stat_scope_id(
                competition_id,
                season,
                stat_type,
                team_provider_id or team_name,
            )
            stats = {
                key: _clean_stat_value(value)
                for key, value in row.values.items()
                if key not in _IDENTITY_STAT_KEYS
            }
            observations.append(
                ExternalPlayerStat(
                    provider=FBREF_PROVIDER,
                    provider_fixture_id=provider_fixture_id,
                    provider_player_id=provider_player_id,
                    team_provider_id=team_provider_id,
                    team_name=team_name or None,
                    display_name=player_name,
                    rating=None,
                    stats=stats,
                    raw_payload={
                        "source_url": source_url,
                        "provider_url": _absolute_url(source_url, player_url),
                        "fbref_table_id": table.table_id,
                        "fbref_raw_row": dict(row.raw),
                    },
                    stat_type=stat_type,
                    season=season,
                    competition=competition,
                    source_url=source_url,
                )
            )
    return observations


def parse_tables(html: str) -> tuple[ParsedTable, ...]:
    parser = _FbrefTableParser()
    parser.feed(_restore_commented_markup(html))
    parser.close()
    return tuple(parser.tables)


class _FbrefTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[ParsedTable] = []
        self._current_table_id: str | None = None
        self._current_caption_chunks: list[str] | None = None
        self._caption: str | None = None
        self._rows: list[ParsedRow] = []
        self._current_row_attrs: dict[str, str] | None = None
        self._current_cells: list[ParsedCell] | None = None
        self._current_cell_data_stat: str | None = None
        self._current_cell_tag: str | None = None
        self._current_cell_chunks: list[str] | None = None
        self._current_cell_links: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag == "table":
            self._current_table_id = attr_map.get("id") or None
            self._caption = None
            self._rows = []
            return
        if self._current_table_id is None and self._rows == []:
            return
        if tag == "caption":
            self._current_caption_chunks = []
            return
        if tag == "tr":
            self._current_row_attrs = attr_map
            self._current_cells = []
            return
        if tag in {"td", "th"} and self._current_cells is not None:
            self._current_cell_tag = tag
            self._current_cell_data_stat = attr_map.get("data-stat") or None
            self._current_cell_chunks = []
            self._current_cell_links = []
            return
        if tag == "a" and self._current_cell_links is not None:
            href = attr_map.get("href")
            if href:
                self._current_cell_links.append(href)

    def handle_data(self, data: str) -> None:
        if self._current_cell_chunks is not None:
            self._current_cell_chunks.append(data)
            return
        if self._current_caption_chunks is not None:
            self._current_caption_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "caption" and self._current_caption_chunks is not None:
            self._caption = _normalize_text("".join(self._current_caption_chunks))
            self._current_caption_chunks = None
            return
        if tag in {"td", "th"} and self._current_cell_chunks is not None:
            assert self._current_cells is not None
            self._current_cells.append(
                ParsedCell(
                    data_stat=self._current_cell_data_stat,
                    text=_normalize_text("".join(self._current_cell_chunks)),
                    links=tuple(self._current_cell_links or ()),
                )
            )
            self._current_cell_tag = None
            self._current_cell_data_stat = None
            self._current_cell_chunks = None
            self._current_cell_links = None
            return
        if tag == "tr" and self._current_cells is not None:
            row = _row_from_cells(self._current_cells, self._current_row_attrs or {})
            if row is not None:
                self._rows.append(row)
            self._current_row_attrs = None
            self._current_cells = None
            return
        if tag == "table" and self._current_table_id is not None:
            self.tables.append(
                ParsedTable(
                    table_id=self._current_table_id,
                    caption=self._caption,
                    rows=tuple(self._rows),
                )
            )
            self._current_table_id = None
            self._caption = None
            self._rows = []


def _row_from_cells(cells: list[ParsedCell], row_attrs: Mapping[str, str]) -> ParsedRow | None:
    if not any(cell.text or cell.links for cell in cells):
        return None
    values: dict[str, str] = {}
    links: dict[str, tuple[str, ...]] = {}
    key_counts: dict[str, int] = {}
    raw_cells: list[dict[str, Any]] = []
    for index, cell in enumerate(cells):
        key = cell.data_stat or f"col_{index}"
        key_count = key_counts.get(key, 0)
        key_counts[key] = key_count + 1
        if key_count:
            key = f"{key}_{key_count + 1}"
        values[key] = cell.text
        links[key] = cell.links
        raw_cells.append(
            {
                "data_stat": cell.data_stat,
                "text": cell.text,
                "links": list(cell.links),
            }
        )
    return ParsedRow(
        values=values,
        links=links,
        raw={"attrs": dict(row_attrs), "cells": raw_cells, "values": dict(values)},
    )


def _fixture_tables(tables: Iterable[ParsedTable]) -> Iterable[ParsedTable]:
    for table in tables:
        if any("home_team" in row.values and "away_team" in row.values for row in table.rows):
            yield table


def _player_tables(tables: Iterable[ParsedTable]) -> Iterable[ParsedTable]:
    for table in tables:
        if any("player" in row.values for row in table.rows):
            yield table


def _restore_commented_markup(html: str) -> str:
    return _COMMENT_RE.sub(lambda match: match.group(1), html)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _value(row: ParsedRow, *keys: str) -> str:
    for key in keys:
        value = row.values.get(key, "").strip()
        if value:
            return value
    return ""


def _first_link(row: ParsedRow, key: str) -> str | None:
    links = row.links.get(key)
    if not links:
        return None
    return links[0]


def _is_empty_row(row: ParsedRow) -> bool:
    return not any(value for value in row.values.values())


def _is_header_row(row: ParsedRow, identity_key: str, *header_values: str) -> bool:
    row_class = str(row.raw.get("attrs", {}).get("class", ""))
    header_labels = {identity_key, *header_values}
    header_value = _value(row, identity_key).lower().replace(" ", "_")
    return "thead" in row_class or header_value in header_labels


def _parse_kickoff(raw_date: str, raw_time: str, timezone_name: str) -> datetime:
    parsed_date = date.fromisoformat(raw_date)
    time_match = _TIME_RE.search(raw_time)
    parsed_time = time.fromisoformat(time_match.group(0)) if time_match else time(0, 0)
    return datetime.combine(parsed_date, parsed_time, ZoneInfo(timezone_name)).astimezone(UTC)


def _fixture_scope_id(
    competition_id: int,
    season: int,
    gameweek: str,
    home_team_provider_id: str,
    away_team_provider_id: str,
) -> str:
    week = gameweek or "unknown-week"
    return f"{competition_id}:{season}:{week}:{home_team_provider_id}:{away_team_provider_id}"


def _stat_scope_id(
    competition_id: int,
    season: int,
    stat_type: str,
    team_identifier: str | None,
) -> str:
    team_scope = _slug(team_identifier or "unknown-team")
    return f"{competition_id}:{season}:{stat_type}:{team_scope}"


def _extract_match_id(url: str | None) -> str | None:
    return _extract_id(_MATCH_ID_RE, url)


def _extract_player_id(url: str | None) -> str | None:
    return _extract_id(_PLAYER_ID_RE, url)


def _extract_squad_id(url: str | None) -> str | None:
    return _extract_id(_SQUAD_ID_RE, url)


def _extract_id(pattern: re.Pattern[str], url: str | None) -> str | None:
    if not url:
        return None
    match = pattern.search(url)
    if match is None:
        return None
    return match.group(1)


def _absolute_url(source_url: str, url: str | None) -> str | None:
    if not url:
        return None
    return urljoin(source_url, url)


def _empty_to_none(value: str) -> str | None:
    return value or None


def _clean_stat_value(value: str) -> object:
    if value == "":
        return None
    candidate = value.replace(",", "")
    if _INTEGER_RE.fullmatch(candidate):
        return int(candidate)
    if _NUMERIC_RE.fullmatch(candidate):
        return float(candidate)
    return value


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"
