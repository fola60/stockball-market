"""Reads the match history the forecasting features are built from.

Works with any DB-API cursor returning mappings (psycopg2 `RealDictCursor`). Nothing here
writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from .features import Appearance, Fixture

PREMIER_LEAGUE = 47
_SCORE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


@dataclass(frozen=True)
class MatchHistory:
    appearances: list[Appearance]
    fixtures: list[Fixture]
    birth_dates: dict[str, date]
    market_values: dict[str, list[tuple[date, float]]]

    @property
    def seasons(self) -> list[int]:
        return sorted({fixture.season for fixture in self.fixtures if fixture.finished})


def _stat(key: str) -> str:
    # FotMob groups a player's match stats under titled sections; the key is stable, the
    # title is display text.
    return (
        "COALESCE((jsonb_path_query_first(r.raw_payload, "
        f"'$.stats[*].stats.* ? (@.key == \"{key}\").stat.value') #>> '{{}}')::float8, 0)"
    )


def load_match_history(cursor: Any, league: int = PREMIER_LEAGUE) -> MatchHistory:
    cursor.execute(
        """
        SELECT match_id, season, kickoff_at, home_team_id, away_team_id, finished,
               raw_fixture #>> '{status,scoreStr}' AS score
        FROM fotmob_matches
        WHERE league_id = %(league)s
        ORDER BY kickoff_at, match_id
        """,
        {"league": league},
    )
    fixtures = []
    for row in cursor.fetchall():
        score = _SCORE.match(row["score"] or "") if row["finished"] else None
        fixtures.append(
            Fixture(
                match_id=str(row["match_id"]),
                season=int(row["season"]),
                kickoff_at=row["kickoff_at"],
                home_team_id=str(row["home_team_id"]),
                away_team_id=str(row["away_team_id"]),
                finished=bool(row["finished"]),
                home_goals=int(score.group(1)) if score else None,
                away_goals=int(score.group(2)) if score else None,
            )
        )

    cursor.execute(
        f"""
        SELECT r.provider_player_id, r.player_id::text AS player_id, r.provider_match_id,
               m.season, m.kickoff_at, r.team_provider_id, r.rating::float8 AS rating,
               COALESCE(r.minutes_played, 0) AS minutes,
               (r.raw_payload ->> 'usualPosition')::int AS position,
               {_stat("goals")} AS goals,
               {_stat("assists")} AS assists,
               {_stat("expected_goals")} AS expected_goals,
               {_stat("expected_assists")} AS expected_assists,
               {_stat("chances_created")} AS chances_created,
               {_stat("defensive_actions")} AS defensive_actions
        FROM player_match_ratings AS r
        JOIN fotmob_matches AS m ON m.match_id = r.provider_match_id
        WHERE m.league_id = %(league)s AND m.finished AND r.minutes_played > 0
        ORDER BY m.kickoff_at, m.match_id
        """,
        {"league": league},
    )
    appearances = [
        Appearance(
            provider_player_id=str(row["provider_player_id"]),
            player_id=row["player_id"],
            match_id=str(row["provider_match_id"]),
            season=int(row["season"]),
            kickoff_at=row["kickoff_at"],
            team_id=str(row["team_provider_id"]),
            rating=None if row["rating"] is None else float(row["rating"]),
            minutes=int(row["minutes"]),
            position=row["position"],
            goals=float(row["goals"]),
            assists=float(row["assists"]),
            expected_goals=float(row["expected_goals"]),
            expected_assists=float(row["expected_assists"]),
            chances_created=float(row["chances_created"]),
            defensive_actions=float(row["defensive_actions"]),
        )
        for row in cursor.fetchall()
    ]

    cursor.execute(
        """
        SELECT DISTINCT ON (matched_player_id)
               matched_player_id::text AS player_id, source_date_of_birth
        FROM market_value_import_rows
        WHERE matched_player_id IS NOT NULL AND source_date_of_birth IS NOT NULL
        ORDER BY matched_player_id, created_at DESC
        """
    )
    birth_dates = {str(row["player_id"]): row["source_date_of_birth"] for row in cursor.fetchall()}

    # Each value is dated by when it was published, so a row only ever sees values that
    # existed at its as-of date.
    cursor.execute(
        """
        SELECT player_id::text AS player_id, observed_at::date AS observed_on,
               value::float8 AS value
        FROM player_market_value_observations
        ORDER BY player_id, observed_at
        """
    )
    market_values: dict[str, list[tuple[date, float]]] = {}
    for row in cursor.fetchall():
        market_values.setdefault(str(row["player_id"]), []).append(
            (row["observed_on"], float(row["value"]))
        )
    return MatchHistory(appearances, fixtures, birth_dates, market_values)
