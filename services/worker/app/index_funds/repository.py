from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Protocol
from uuid import UUID

from psycopg2.extras import RealDictCursor

from app.database import connection as pooled_connection

from .models import TEAM_INDEX_KIND, TeamRoster


class TeamIndexFundRepository(Protocol):
    def team_rosters(self, season: int) -> list[TeamRoster]: ...

    def existing_team_funds(self) -> dict[str, str]: ...


class PostgresTeamIndexFundRepository:
    """Read-only: index funds are created by the trading engine."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _cursor(self) -> Iterator[RealDictCursor]:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor

    def team_rosters(self, season: int) -> list[TeamRoster]:
        """Each club's listed players in this season's league roster.

        Players halted for any reason but a match day (those who left the league, or a manual
        halt) stay out, so a fund never starts with a share that cannot trade for weeks.
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT p.club, i.id AS instrument_id
                FROM instruments AS i
                JOIN players AS p ON p.id = i.player_id
                WHERE i.instrument_type = 'PLAYER_SHARE'
                  AND i.trading_status <> 'DELISTED'
                  AND p.club IS NOT NULL
                  AND COALESCE(p.metadata ->> 'season', '') = %(season)s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM instrument_freezes AS f
                      WHERE f.instrument_id = i.id
                        AND f.released_at IS NULL
                        AND f.reason <> 'MATCH_DAY'
                  )
                ORDER BY p.club, i.id
                """,
                {"season": str(season)},
            )
            rows = cursor.fetchall()
        rosters: dict[str, list[UUID]] = {}
        for row in rows:
            rosters.setdefault(str(row["club"]), []).append(UUID(str(row["instrument_id"])))
        return [TeamRoster(club, tuple(ids)) for club, ids in rosters.items()]

    def existing_team_funds(self) -> dict[str, str]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT f.club, i.symbol
                FROM index_funds AS f
                JOIN instruments AS i ON i.id = f.instrument_id
                WHERE f.index_kind = %(kind)s
                """,
                {"kind": TEAM_INDEX_KIND},
            )
            rows = cursor.fetchall()
        return {str(row["club"]): str(row["symbol"]) for row in rows}
