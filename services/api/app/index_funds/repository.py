from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator, Protocol
from uuid import UUID

from psycopg2.extras import RealDictCursor

from app.common.decimal import format_decimal
from app.database import connection as pooled_connection
from app.index_funds.models import IndexConstituentRecord, IndexFundRecord
from app.instruments.models import InstrumentStatus


class IndexFundsRepository(Protocol):
    def list_index_funds(self) -> list[IndexFundRecord]: ...

    def get_index_fund(self, instrument_id: UUID) -> IndexFundRecord | None: ...

    def list_constituents(self, instrument_id: UUID) -> list[IndexConstituentRecord]: ...


_FUND_QUERY = """
    SELECT
        i.id,
        i.symbol,
        i.display_name,
        fund.index_kind,
        fund.club,
        i.current_price,
        CASE
            WHEN i.trading_status <> 'ACTIVE' THEN i.trading_status
            WHEN basket.frozen_count > 0 THEN 'FROZEN'
            ELSE 'ACTIVE'
        END AS status,
        basket.freeze_reason,
        basket.constituent_count,
        COALESCE(units.outstanding, 0) AS units_outstanding,
        COALESCE(ROUND(((i.current_price - opening.opening_price)
            / NULLIF(opening.opening_price, 0)) * 100, 4), 0) AS price_change_24h,
        COALESCE(ROUND(((i.current_price - week_opening.opening_price)
            / NULLIF(week_opening.opening_price, 0)) * 100, 4), 0) AS price_change_7d,
        COALESCE(activity.volume_24h, 0) AS volume_24h,
        ROUND(COALESCE(activity.traded_value_24h, 0), 4) AS traded_value_24h,
        left(badge.content_sha256, 16) AS club_badge_version,
        i.created_at,
        i.updated_at
    FROM instruments AS i
    JOIN index_funds AS fund ON fund.instrument_id = i.id
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) AS constituent_count,
            COUNT(*) FILTER (WHERE member.trading_status <> 'ACTIVE') AS frozen_count,
            (
                SELECT f.reason
                FROM index_constituents AS c
                JOIN instrument_freezes AS f
                    ON f.instrument_id = c.constituent_instrument_id AND f.released_at IS NULL
                WHERE c.index_instrument_id = i.id
                ORDER BY f.reason <> 'MATCH_DAY', f.started_at
                LIMIT 1
            ) AS freeze_reason
        FROM index_constituents AS constituent
        JOIN instruments AS member ON member.id = constituent.constituent_instrument_id
        WHERE constituent.index_instrument_id = i.id
    ) AS basket ON TRUE
    LEFT JOIN LATERAL (
        SELECT SUM(quantity) AS outstanding
        FROM positions
        WHERE instrument_id = i.id
    ) AS units ON TRUE
    LEFT JOIN LATERAL (
        SELECT ps.old_price AS opening_price
        FROM price_snapshots AS ps
        WHERE ps.instrument_id = i.id
          AND ps.captured_at >= now() - interval '24 hours'
        ORDER BY ps.captured_at ASC, ps.id ASC
        LIMIT 1
    ) AS opening ON TRUE
    LEFT JOIN LATERAL (
        SELECT ps.old_price AS opening_price
        FROM price_snapshots AS ps
        WHERE ps.instrument_id = i.id
          AND ps.captured_at >= now() - interval '7 days'
        ORDER BY ps.captured_at ASC, ps.id ASC
        LIMIT 1
    ) AS week_opening ON TRUE
    LEFT JOIN LATERAL (
        SELECT SUM(t.shares) AS volume_24h, SUM(t.gross_amount) AS traded_value_24h
        FROM trades AS t
        WHERE t.instrument_id = i.id
          AND t.executed_at >= now() - interval '24 hours'
    ) AS activity ON TRUE
    LEFT JOIN fotmob_club_teams AS club_team ON club_team.club = fund.club
    LEFT JOIN fotmob_team_logos AS badge
        ON badge.provider_team_id = club_team.provider_team_id
       AND badge.status = 'READY'
    WHERE i.instrument_type = 'INDEX_FUND'
"""


class PostgresIndexFundsRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _cursor(self) -> Iterator[RealDictCursor]:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor

    def list_index_funds(self) -> list[IndexFundRecord]:
        with self._cursor() as cursor:
            cursor.execute(_FUND_QUERY + " ORDER BY fund.club, i.symbol")
            rows = cursor.fetchall()
        return [_fund(row) for row in rows]

    def get_index_fund(self, instrument_id: UUID) -> IndexFundRecord | None:
        with self._cursor() as cursor:
            cursor.execute(
                _FUND_QUERY + " AND i.id = %(instrument_id)s",
                {"instrument_id": str(instrument_id)},
            )
            row = cursor.fetchone()
        return None if row is None else _fund(row)

    def list_constituents(self, instrument_id: UUID) -> list[IndexConstituentRecord]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    member.id AS instrument_id,
                    member.symbol,
                    player.display_name AS player_name,
                    player.position AS player_position,
                    member.trading_status AS status,
                    constituent.shares_per_unit,
                    member.current_price,
                    ROUND(
                        constituent.shares_per_unit * member.current_price * 100
                            / NULLIF(SUM(constituent.shares_per_unit * member.current_price)
                                OVER (), 0),
                        2
                    ) AS weight,
                    COALESCE(ROUND(((member.current_price - opening.opening_price)
                        / NULLIF(opening.opening_price, 0)) * 100, 4), 0) AS price_change_24h,
                    left(portrait.content_sha256, 16) AS player_image_version
                FROM index_constituents AS constituent
                JOIN instruments AS member ON member.id = constituent.constituent_instrument_id
                JOIN players AS player ON player.id = member.player_id
                LEFT JOIN LATERAL (
                    SELECT ps.old_price AS opening_price
                    FROM price_snapshots AS ps
                    WHERE ps.instrument_id = member.id
                      AND ps.captured_at >= now() - interval '24 hours'
                    ORDER BY ps.captured_at ASC, ps.id ASC
                    LIMIT 1
                ) AS opening ON TRUE
                LEFT JOIN LATERAL (
                    SELECT image.content_sha256
                    FROM player_provider_refs AS ref
                    JOIN fotmob_player_images AS image
                        ON image.provider_player_id = ref.provider_player_id
                       AND image.status = 'READY'
                    WHERE ref.provider = 'FOTMOB' AND ref.player_id = player.id
                    ORDER BY ref.is_primary DESC, image.fetched_at DESC
                    LIMIT 1
                ) AS portrait ON TRUE
                WHERE constituent.index_instrument_id = %(instrument_id)s
                ORDER BY constituent.shares_per_unit * member.current_price DESC, member.id
                """,
                {"instrument_id": str(instrument_id)},
            )
            rows = cursor.fetchall()
        return [
            IndexConstituentRecord(
                instrument_id=UUID(str(row["instrument_id"])),
                symbol=row["symbol"],
                player_name=row["player_name"],
                player_position=row["player_position"],
                status=InstrumentStatus(row["status"]),
                shares_per_unit=format_decimal(Decimal(row["shares_per_unit"]).normalize()),
                current_price=format_decimal(Decimal(row["current_price"])),
                weight=format_decimal(Decimal(row["weight"] or 0)),
                price_change_24h=format_decimal(Decimal(row["price_change_24h"])),
                player_image_version=row["player_image_version"],
            )
            for row in rows
        ]


def _fund(row: dict) -> IndexFundRecord:
    return IndexFundRecord(
        id=UUID(str(row["id"])),
        symbol=row["symbol"],
        display_name=row["display_name"],
        index_kind=row["index_kind"],
        club=row["club"],
        current_price=format_decimal(Decimal(row["current_price"])),
        status=InstrumentStatus(row["status"]),
        freeze_reason=row["freeze_reason"],
        constituent_count=int(row["constituent_count"]),
        units_outstanding=format_decimal(Decimal(row["units_outstanding"]).normalize()),
        price_change_24h=format_decimal(Decimal(row["price_change_24h"])),
        price_change_7d=format_decimal(Decimal(row["price_change_7d"])),
        volume_24h=format_decimal(Decimal(row["volume_24h"])),
        traded_value_24h=format_decimal(Decimal(row["traded_value_24h"])),
        club_badge_version=row["club_badge_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
