from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Protocol
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.database import connection as pooled_connection

from .models import ROSTER_SOURCE_PREFIX, RosterMembership


class LeagueRosterRepository(Protocol):
    def memberships(self, season: int) -> list[RosterMembership]: ...

    def open_roster_freezes(self) -> dict[str, set[UUID]]: ...


class PostgresLeagueRosterRepository:
    """Read-only: freezes are opened and released by the trading engine."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _cursor(self) -> Iterator[psycopg2.extensions.cursor]:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor

    def memberships(self, season: int) -> list[RosterMembership]:
        """Every listed player share, and whether its player is in this season's roster.

        Player ingestion stamps each player with the latest season it was listed in.
        """
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT i.id AS instrument_id, p.id AS player_id,
                       COALESCE(p.metadata ->> 'season', '') = %(season)s AS in_league
                FROM instruments AS i
                JOIN players AS p ON p.id = i.player_id
                WHERE i.instrument_type = 'PLAYER_SHARE'
                  AND i.trading_status <> 'DELISTED'
                """,
                {"season": str(season)},
            )
            rows = cursor.fetchall()
        return [
            RosterMembership(
                instrument_id=UUID(str(row["instrument_id"])),
                player_id=UUID(str(row["player_id"])),
                in_league=bool(row["in_league"]),
            )
            for row in rows
        ]

    def open_roster_freezes(self) -> dict[str, set[UUID]]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT source_key, instrument_id
                FROM instrument_freezes
                WHERE released_at IS NULL
                  AND source_key LIKE %(prefix)s
                """,
                {"prefix": f"{ROSTER_SOURCE_PREFIX}%"},
            )
            rows = cursor.fetchall()
        open_freezes: dict[str, set[UUID]] = {}
        for row in rows:
            open_freezes.setdefault(str(row["source_key"]), set()).add(
                UUID(str(row["instrument_id"]))
            )
        return open_freezes
