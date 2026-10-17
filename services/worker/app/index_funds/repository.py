from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Protocol
from uuid import UUID

from psycopg2.extras import RealDictCursor

from app.database import connection as pooled_connection

from .models import TEAM_INDEX_KIND, TeamFund, TeamRoster


class IndexFundRepository(Protocol):
    def team_rosters(self, season: int) -> list[TeamRoster]: ...

    def team_funds(self) -> list[TeamFund]: ...


class PostgresIndexFundRepository:
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

    def team_funds(self) -> list[TeamFund]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    fund.instrument_id,
                    i.symbol,
                    fund.club,
                    fund.cash_per_unit,
                    i.current_price,
                    member.constituent_instrument_id AS member_id,
                    EXISTS (
                        SELECT 1
                        FROM instrument_freezes AS f
                        WHERE f.instrument_id = member.constituent_instrument_id
                          AND f.released_at IS NULL
                          AND f.reason <> 'MATCH_DAY'
                    ) AS halted
                FROM index_funds AS fund
                JOIN instruments AS i ON i.id = fund.instrument_id
                LEFT JOIN index_constituents AS member
                    ON member.index_instrument_id = fund.instrument_id
                WHERE fund.index_kind = %(kind)s
                  AND i.trading_status <> 'DELISTED'
                ORDER BY fund.club, member.constituent_instrument_id
                """,
                {"kind": TEAM_INDEX_KIND},
            )
            rows = cursor.fetchall()
        funds: dict[UUID, dict] = {}
        for row in rows:
            fund_id = UUID(str(row["instrument_id"]))
            fund = funds.setdefault(
                fund_id,
                {"symbol": str(row["symbol"]), "club": str(row["club"]), "members": set(),
                 "halted": set(), "cash": str(row["cash_per_unit"]),
                 "price": str(row["current_price"])},
            )
            if row["member_id"] is not None:
                member = UUID(str(row["member_id"]))
                fund["members"].add(member)
                if row["halted"]:
                    fund["halted"].add(member)
        return [
            TeamFund(
                instrument_id=fund_id,
                symbol=fund["symbol"],
                club=fund["club"],
                members=frozenset(fund["members"]),
                halted_members=frozenset(fund["halted"]),
                cash_per_unit=fund["cash"],
                unit_price=fund["price"],
            )
            for fund_id, fund in funds.items()
        ]
