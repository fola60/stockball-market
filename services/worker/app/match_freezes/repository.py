from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Protocol, Sequence
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.database import connection as pooled_connection

from .models import FIXTURE_SOURCE_PREFIX, FixtureRecord, MatchFreezeWindow


class MatchFreezeRepository(Protocol):
    def fixtures_near(self, now: datetime, window: MatchFreezeWindow) -> Sequence[FixtureRecord]: ...

    def instruments_for_teams(self, team_provider_ids: Sequence[str]) -> dict[str, set[UUID]]: ...

    def open_fixture_freezes(self) -> dict[str, set[UUID]]: ...


class PostgresMatchFreezeRepository:
    """Read-only: freezes are opened and released by the trading engine."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _cursor(self) -> Iterator[psycopg2.extensions.cursor]:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor

    def fixtures_near(self, now: datetime, window: MatchFreezeWindow) -> list[FixtureRecord]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT id, kickoff_at, home_team_provider_id, away_team_provider_id,
                       home_team_name, away_team_name, status_short
                FROM fixtures
                WHERE kickoff_at <= %(now)s + %(lineup_lock)s
                  AND kickoff_at > %(now)s - %(settlement)s
                ORDER BY kickoff_at, id
                """,
                {"now": now, "lineup_lock": window.lineup_lock, "settlement": window.settlement},
            )
            rows = cursor.fetchall()
        return [
            FixtureRecord(
                fixture_id=UUID(str(row["id"])),
                kickoff_at=row["kickoff_at"],
                home_team_provider_id=str(row["home_team_provider_id"]),
                away_team_provider_id=str(row["away_team_provider_id"]),
                home_team_name=str(row["home_team_name"]),
                away_team_name=str(row["away_team_name"]),
                status_short=row["status_short"],
            )
            for row in rows
        ]

    def instruments_for_teams(self, team_provider_ids: Sequence[str]) -> dict[str, set[UUID]]:
        if not team_provider_ids:
            return {}
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT player.metadata->>'team_provider_id' AS team_provider_id, i.id
                FROM instruments AS i
                JOIN players AS player ON player.id = i.player_id
                WHERE i.instrument_type = 'PLAYER_SHARE'
                  AND i.trading_status <> 'DELISTED'
                  AND player.metadata->>'team_provider_id' = ANY(%(teams)s)
                """,
                {"teams": list(team_provider_ids)},
            )
            rows = cursor.fetchall()
        by_team: dict[str, set[UUID]] = {}
        for row in rows:
            by_team.setdefault(str(row["team_provider_id"]), set()).add(UUID(str(row["id"])))
        return by_team

    def open_fixture_freezes(self) -> dict[str, set[UUID]]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT source_key, instrument_id
                FROM instrument_freezes
                WHERE released_at IS NULL
                  AND source_key LIKE %(prefix)s
                """,
                {"prefix": f"{FIXTURE_SOURCE_PREFIX}%"},
            )
            rows = cursor.fetchall()
        open_freezes: dict[str, set[UUID]] = {}
        for row in rows:
            open_freezes.setdefault(str(row["source_key"]), set()).add(
                UUID(str(row["instrument_id"]))
            )
        return open_freezes
