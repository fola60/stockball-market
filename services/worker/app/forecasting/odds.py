"""Match result odds from football-data.co.uk's public season files, linked to FotMob fixtures.

One CSV per season lists every Premier League match with bookmakers' closing 1X2 prices. The
file for the season in progress is updated as matches are played, so importing it again adds
the latest rounds. Earlier seasons are a one-off backfill.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence

from psycopg2.extras import RealDictCursor, execute_values

from app.database import connection as pooled_connection

from .dataset import PREMIER_LEAGUE

SOURCE = "football-data.co.uk"
SEASON_URL = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"
# Market average first, then individual books, for seasons or rows where it is missing.
PRICE_COLUMNS = (("AvgH", "AvgD", "AvgA"), ("PSH", "PSD", "PSA"), ("B365H", "B365D", "B365A"))
# Short names the source uses that share no leading word with FotMob's.
TEAM_ALIASES = {
    "man united": "manchester united",
    "man city": "manchester city",
    "nottm forest": "nottingham forest",
    "wolves": "wolverhampton wanderers",
    "spurs": "tottenham hotspur",
}


@dataclass(frozen=True)
class SourceOdds:
    match_date: date
    home_team: str
    away_team: str
    home_probability: float
    draw_probability: float
    away_probability: float


def season_url(season: int) -> str:
    """The file for the season starting in `season`: 2025 is 2025-26, code 2526."""
    return SEASON_URL.format(code=f"{season % 100:02d}{(season + 1) % 100:02d}")


def download_season(season: int, timeout_seconds: float = 30.0) -> str:
    import httpx

    response = httpx.get(season_url(season), timeout=timeout_seconds, follow_redirects=True)
    response.raise_for_status()
    return response.text


def parse_match_odds(text: str) -> list[SourceOdds]:
    """Rows with a date, both teams and a full set of prices; the rest are skipped."""
    rows = []
    for record in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        match_date = _date(record.get("Date"))
        home, away = (record.get("HomeTeam") or "").strip(), (record.get("AwayTeam") or "").strip()
        probabilities = _probabilities(record)
        if match_date is None or not home or not away or probabilities is None:
            continue
        rows.append(SourceOdds(match_date, home, away, *probabilities))
    return rows


def import_match_odds(
    database_url: str, csv_texts: Iterable[str], *, league: int = PREMIER_LEAGUE
) -> dict[str, Any]:
    """Link each source row to the FotMob fixture with the same teams within a day of its
    date, and store the probabilities. Rows that match no fixture, or more than one, are
    reported and left out."""
    odds = [row for text in csv_texts for row in parse_match_odds(text)]
    with pooled_connection(database_url) as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT match_id, kickoff_at, home_team_name, away_team_name
                FROM fotmob_matches
                WHERE league_id = %s
                """,
                (league,),
            )
            fixtures = cursor.fetchall()
    by_date: dict[date, list[Any]] = {}
    for fixture in fixtures:
        by_date.setdefault(fixture["kickoff_at"].date(), []).append(fixture)

    matched: dict[str, SourceOdds] = {}
    unmatched: list[str] = []
    for row in odds:
        match_id = _match(row, by_date)
        if match_id is None:
            unmatched.append(f"{row.match_date} {row.home_team} v {row.away_team}")
        else:
            matched[match_id] = row
    if matched:
        with pooled_connection(database_url) as connection:
            with connection.cursor() as cursor:
                execute_values(
                    cursor,
                    """
                    INSERT INTO match_result_odds (
                        match_id, source, home_probability, draw_probability,
                        away_probability, source_home_team, source_away_team,
                        source_match_date
                    )
                    VALUES %s
                    ON CONFLICT (match_id) DO UPDATE
                    SET source = EXCLUDED.source,
                        home_probability = EXCLUDED.home_probability,
                        draw_probability = EXCLUDED.draw_probability,
                        away_probability = EXCLUDED.away_probability,
                        source_home_team = EXCLUDED.source_home_team,
                        source_away_team = EXCLUDED.source_away_team,
                        source_match_date = EXCLUDED.source_match_date,
                        imported_at = now()
                    """,
                    [
                        (
                            match_id,
                            SOURCE,
                            round(row.home_probability, 5),
                            round(row.draw_probability, 5),
                            round(row.away_probability, 5),
                            row.home_team,
                            row.away_team,
                            row.match_date,
                        )
                        for match_id, row in matched.items()
                    ],
                )
    return {
        "source_rows": len(odds),
        "matched": len(matched),
        "unmatched": len(unmatched),
        "unmatched_examples": unmatched[:10],
    }


def _match(row: SourceOdds, by_date: dict[date, list[Any]]) -> str | None:
    """The one fixture around the row's date whose two teams both look like the row's."""
    scored = []
    for offset in (0, -1, 1):
        for fixture in by_date.get(row.match_date + timedelta(days=offset), ()):
            home = _name_score(row.home_team, fixture["home_team_name"])
            away = _name_score(row.away_team, fixture["away_team_name"])
            if home and away:
                scored.append((home + away, str(fixture["match_id"])))
    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def _name_score(source: str, fotmob: str) -> int:
    """3 for the same name, 2 when one starts the other, 1 for a shared first word."""
    left, right = _normalise(source), _normalise(fotmob)
    if not left or not right:
        return 0
    if left == right:
        return 3
    if left.startswith(right) or right.startswith(left):
        return 2
    return 1 if left.split()[0] == right.split()[0] else 0


def _normalise(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z ]", "", text).strip()
    text = TEAM_ALIASES.get(text, text)
    return re.sub(r"^(afc|fc) ", "", text)


def _date(value: str | None) -> date | None:
    text = (value or "").strip()
    for pattern in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _probabilities(record: dict[str, Any]) -> tuple[float, float, float] | None:
    for columns in PRICE_COLUMNS:
        try:
            prices = [float(record.get(column) or "") for column in columns]
        except ValueError:
            continue
        if all(price > 1.0 for price in prices):
            implied = [1.0 / price for price in prices]
            total = sum(implied)
            # Dividing by the total removes the bookmaker's margin.
            return implied[0] / total, implied[1] / total, implied[2] / total
    return None


def refresh_current_season(database_url: str, season: int) -> dict[str, Any]:
    return import_match_odds(database_url, [download_season(season)])


def read_csv_files(paths: Sequence[str]) -> list[str]:
    texts = []
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            texts.append(handle.read())
    return texts
