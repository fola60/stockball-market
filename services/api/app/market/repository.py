from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterator, Protocol
from uuid import UUID

from psycopg2.extras import RealDictCursor

from app.common.decimal import format_decimal
from app.common.images import ImageRecord
from app.database import connection as pooled_connection
from app.market.models import (
    FixtureRowRecord,
    FixtureTeamRecord,
    MarketTradeRecord,
    NewsCandidateRecord,
    RatedPlayerRecord,
)
from app.traders.models import TraderKind

# Stockball V1 lists Premier League players only; FotMob's ID for that league.
PREMIER_LEAGUE_ID = 47


class MarketRepository(Protocol):
    def sparklines(
        self, instrument_ids: list[UUID], window: timedelta, step: timedelta
    ) -> dict[UUID, list[str]]: ...

    def upcoming_round(self) -> tuple[int, int] | None: ...

    def latest_season(self) -> int | None: ...

    def round_fixtures(self, season: int, round_number: int) -> list[FixtureRowRecord]: ...

    def latest_finished_round(self, season: int, before: int | None) -> int | None: ...

    def top_rated(self, season: int, round_number: int, limit: int) -> list[RatedPlayerRecord]: ...

    def league_clubs(self, season: int) -> list[str]: ...

    def recent_trades(self, window: timedelta, limit: int) -> list[MarketTradeRecord]: ...

    def news_candidates(self, since: datetime, limit: int) -> list[NewsCandidateRecord]: ...

    def club_names(self) -> dict[str, list[str]]: ...

    def team_badge(self, team_id: str) -> ImageRecord | None: ...


class PostgresMarketRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _cursor(self) -> Iterator[RealDictCursor]:
        with pooled_connection(self._database_url) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor

    def sparklines(
        self, instrument_ids: list[UUID], window: timedelta, step: timedelta
    ) -> dict[UUID, list[str]]:
        if not instrument_ids:
            return {}
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    i.id AS instrument_id,
                    COALESCE(
                        (
                            SELECT ps.new_price
                            FROM price_snapshots AS ps
                            WHERE ps.instrument_id = i.id AND ps.captured_at <= g.at
                            ORDER BY ps.captured_at DESC, ps.id DESC
                            LIMIT 1
                        ),
                        first_snapshot.old_price,
                        i.current_price
                    ) AS price
                FROM instruments AS i
                LEFT JOIN LATERAL (
                    SELECT ps.old_price
                    FROM price_snapshots AS ps
                    WHERE ps.instrument_id = i.id
                    ORDER BY ps.captured_at, ps.id
                    LIMIT 1
                ) AS first_snapshot ON TRUE
                CROSS JOIN generate_series(now() - %(window)s, now(), %(step)s) AS g(at)
                WHERE i.id = ANY(%(ids)s::uuid[])
                ORDER BY i.id, g.at
                """,
                {
                    "ids": [str(instrument_id) for instrument_id in instrument_ids],
                    "window": window,
                    "step": step,
                },
            )
            rows = cursor.fetchall()

        series: dict[UUID, list[str]] = {}
        for row in rows:
            series.setdefault(row["instrument_id"], []).append(
                format_decimal(Decimal(row["price"]).quantize(Decimal("0.0001")))
            )
        return series

    def upcoming_round(self) -> tuple[int, int] | None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT season, (raw_fixture->>'round')::int AS round_number
                FROM fotmob_matches
                WHERE league_id = %(league)s
                  AND NOT finished
                  AND kickoff_at > now() - interval '4 hours'
                  AND NOT COALESCE((raw_fixture->'status'->>'cancelled')::boolean, false)
                  AND raw_fixture->>'round' ~ '^[0-9]+$'
                ORDER BY kickoff_at, match_id
                LIMIT 1
                """,
                {"league": PREMIER_LEAGUE_ID},
            )
            row = cursor.fetchone()
        return None if row is None else (row["season"], row["round_number"])

    def latest_season(self) -> int | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT max(season) AS season FROM fotmob_matches WHERE league_id = %(league)s",
                {"league": PREMIER_LEAGUE_ID},
            )
            row = cursor.fetchone()
        return None if row is None else row["season"]

    def round_fixtures(self, season: int, round_number: int) -> list[FixtureRowRecord]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    m.match_id,
                    m.kickoff_at,
                    m.finished,
                    COALESCE((m.raw_fixture->'status'->>'started')::boolean, false) AS started,
                    COALESCE((m.raw_fixture->'status'->>'cancelled')::boolean, false) AS cancelled,
                    m.raw_fixture->'status'->>'scoreStr' AS score,
                    m.home_team_id,
                    m.home_team_name,
                    COALESCE(m.raw_fixture->'home'->>'shortName', m.home_team_name) AS home_short_name,
                    home_club.club AS home_club,
                    left(home_logo.content_sha256, 16) AS home_badge_version,
                    m.away_team_id,
                    m.away_team_name,
                    COALESCE(m.raw_fixture->'away'->>'shortName', m.away_team_name) AS away_short_name,
                    away_club.club AS away_club,
                    left(away_logo.content_sha256, 16) AS away_badge_version
                FROM fotmob_matches AS m
                LEFT JOIN LATERAL (
                    SELECT ct.club
                    FROM fotmob_club_teams AS ct
                    WHERE ct.provider_team_id = m.home_team_id
                    ORDER BY ct.linked_players DESC, ct.club
                    LIMIT 1
                ) AS home_club ON TRUE
                LEFT JOIN LATERAL (
                    SELECT ct.club
                    FROM fotmob_club_teams AS ct
                    WHERE ct.provider_team_id = m.away_team_id
                    ORDER BY ct.linked_players DESC, ct.club
                    LIMIT 1
                ) AS away_club ON TRUE
                LEFT JOIN fotmob_team_logos AS home_logo
                    ON home_logo.provider_team_id = m.home_team_id AND home_logo.status = 'READY'
                LEFT JOIN fotmob_team_logos AS away_logo
                    ON away_logo.provider_team_id = m.away_team_id AND away_logo.status = 'READY'
                WHERE m.league_id = %(league)s
                  AND m.season = %(season)s
                  AND m.raw_fixture->>'round' = %(round)s
                ORDER BY m.kickoff_at, m.match_id
                """,
                {"league": PREMIER_LEAGUE_ID, "season": season, "round": str(round_number)},
            )
            rows = cursor.fetchall()

        return [
            FixtureRowRecord(
                match_id=row["match_id"],
                kickoff_at=row["kickoff_at"],
                finished=row["finished"],
                started=row["started"],
                cancelled=row["cancelled"],
                score=row["score"],
                home=_team(row, "home"),
                away=_team(row, "away"),
            )
            for row in rows
        ]

    def latest_finished_round(self, season: int, before: int | None) -> int | None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT max((raw_fixture->>'round')::int) AS round_number
                FROM fotmob_matches
                WHERE league_id = %(league)s
                  AND season = %(season)s
                  AND finished
                  AND raw_fixture->>'round' ~ '^[0-9]+$'
                  AND (%(before)s::int IS NULL OR (raw_fixture->>'round')::int < %(before)s::int)
                """,
                {"league": PREMIER_LEAGUE_ID, "season": season, "before": before},
            )
            row = cursor.fetchone()
        return None if row is None else row["round_number"]

    def top_rated(self, season: int, round_number: int, limit: int) -> list[RatedPlayerRecord]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    i.id AS instrument_id,
                    p.display_name AS player_name,
                    r.team_name,
                    r.rating,
                    CASE WHEN jsonb_typeof(goals.value) = 'number'
                        THEN (goals.value)::text::numeric::int
                        ELSE 0
                    END AS goals,
                    COALESCE(m.raw_fixture->'home'->>'shortName', m.home_team_name) AS home_team,
                    COALESCE(m.raw_fixture->'away'->>'shortName', m.away_team_name) AS away_team,
                    m.raw_fixture->'status'->>'scoreStr' AS score
                FROM player_match_ratings AS r
                JOIN fotmob_matches AS m ON m.match_id = r.provider_match_id
                JOIN players AS p ON p.id = r.player_id
                JOIN instruments AS i ON i.player_id = p.id AND i.trading_status <> 'DELISTED'
                LEFT JOIN LATERAL (
                    SELECT jsonb_path_query_first(
                        r.raw_payload, '$.stats[*].stats.Goals.stat.value'
                    ) AS value
                ) AS goals ON TRUE
                WHERE m.league_id = %(league)s
                  AND m.season = %(season)s
                  AND m.raw_fixture->>'round' = %(round)s
                  AND r.rating IS NOT NULL
                ORDER BY r.rating DESC, r.minutes_played DESC NULLS LAST, p.display_name
                LIMIT %(limit)s
                """,
                {
                    "league": PREMIER_LEAGUE_ID,
                    "season": season,
                    "round": str(round_number),
                    "limit": limit,
                },
            )
            rows = cursor.fetchall()

        return [
            RatedPlayerRecord(
                instrument_id=row["instrument_id"],
                player_name=row["player_name"],
                team_name=row["team_name"],
                rating=format_decimal(Decimal(row["rating"]).quantize(Decimal("0.01"))),
                goals=row["goals"],
                home_team=row["home_team"],
                away_team=row["away_team"],
                score=row["score"],
            )
            for row in rows
        ]

    def league_clubs(self, season: int) -> list[str]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ct.club
                FROM fotmob_matches AS m
                JOIN fotmob_club_teams AS ct
                    ON ct.provider_team_id IN (m.home_team_id, m.away_team_id)
                WHERE m.league_id = %(league)s AND m.season = %(season)s
                ORDER BY ct.club
                """,
                {"league": PREMIER_LEAGUE_ID, "season": season},
            )
            return [row["club"] for row in cursor.fetchall()]

    def recent_trades(self, window: timedelta, limit: int) -> list[MarketTradeRecord]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    t.id AS trade_id,
                    t.executed_at,
                    t.side,
                    t.shares,
                    t.execution_price,
                    t.gross_amount,
                    t.instrument_id,
                    p.display_name AS player_name,
                    a.id AS account_id,
                    a.display_name AS trader_name,
                    a.account_type,
                    config.display_name AS strategy
                FROM trades AS t
                JOIN accounts AS a ON a.id = t.account_id
                JOIN instruments AS i ON i.id = t.instrument_id
                JOIN players AS p ON p.id = i.player_id
                LEFT JOIN synthetic_trader_bots AS bot ON bot.account_id = a.id
                LEFT JOIN synthetic_trader_bot_configs AS config ON config.id = bot.config_id
                WHERE t.executed_at >= now() - %(window)s
                  AND a.account_type IN ('USER', 'SYNTHETIC_TRADER')
                ORDER BY t.gross_amount DESC, t.executed_at DESC, t.id
                LIMIT %(limit)s
                """,
                {"window": window, "limit": limit},
            )
            rows = cursor.fetchall()

        return [
            MarketTradeRecord(
                trade_id=row["trade_id"],
                executed_at=row["executed_at"],
                account_id=row["account_id"],
                trader_name=row["trader_name"],
                trader_kind=(
                    TraderKind.BOT if row["account_type"] == "SYNTHETIC_TRADER" else TraderKind.PERSON
                ),
                strategy=row["strategy"],
                side=row["side"],
                shares=format_decimal(Decimal(row["shares"]).quantize(Decimal("0.000001"))),
                execution_price=format_decimal(
                    Decimal(row["execution_price"]).quantize(Decimal("0.0001"))
                ),
                gross_amount=format_decimal(Decimal(row["gross_amount"]).quantize(Decimal("0.0001"))),
                instrument_id=row["instrument_id"],
                player_name=row["player_name"],
            )
            for row in rows
        ]

    def news_candidates(self, since: datetime, limit: int) -> list[NewsCandidateRecord]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    d.id AS document_id,
                    d.provider_metadata->>'title' AS title,
                    COALESCE(d.normalized_text, '') AS text,
                    d.canonical_url AS url,
                    s.display_handle AS source,
                    d.published_at,
                    o.topic,
                    o.resolution_confidence,
                    p.display_name AS player_name,
                    p.club,
                    i.id AS instrument_id
                FROM social_documents AS d
                JOIN social_sources AS s ON s.id = d.source_id
                JOIN social_observations AS o ON o.document_id = d.id
                JOIN players AS p ON p.id = o.player_id
                JOIN instruments AS i ON i.player_id = p.id AND i.trading_status <> 'DELISTED'
                WHERE d.provider = 'RSS'
                  AND d.deleted_at IS NULL
                  AND d.published_at >= %(since)s
                  AND d.provider_metadata ? 'title'
                  AND s.enabled
                  AND s.policy_status = 'APPROVED'
                  AND s.source_category IN ('NEWS_ORGANISATION', 'COMMUNITY')
                  AND o.entity_type = 'PLAYER'
                  AND o.resolution_status = 'RESOLVED'
                  AND o.invalidated_at IS NULL
                ORDER BY d.published_at DESC, o.resolution_confidence DESC NULLS LAST
                LIMIT %(limit)s
                """,
                {"since": since, "limit": limit},
            )
            rows = cursor.fetchall()

        return [
            NewsCandidateRecord(
                document_id=row["document_id"],
                title=row["title"],
                text=row["text"],
                url=row["url"],
                source=row["source"],
                published_at=row["published_at"],
                topic=row["topic"],
                resolution_confidence=float(row["resolution_confidence"] or 0),
                player_name=row["player_name"],
                club=row["club"],
                instrument_id=row["instrument_id"],
            )
            for row in rows
        ]

    def club_names(self) -> dict[str, list[str]]:
        """Every name FotMob uses for each canonical club's team."""
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT ct.club, array_remove(array_agg(DISTINCT names.name), NULL) AS names
                FROM fotmob_club_teams AS ct
                LEFT JOIN LATERAL (
                    SELECT m.home_team_name AS name
                    FROM fotmob_matches AS m
                    WHERE m.home_team_id = ct.provider_team_id
                    UNION
                    SELECT m.raw_fixture->'home'->>'shortName'
                    FROM fotmob_matches AS m
                    WHERE m.home_team_id = ct.provider_team_id
                ) AS names ON TRUE
                GROUP BY ct.club
                """
            )
            return {row["club"]: list(row["names"]) for row in cursor.fetchall()}

    def team_badge(self, team_id: str) -> ImageRecord | None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT image_data, content_type, content_sha256
                FROM fotmob_team_logos
                WHERE provider_team_id = %(team_id)s AND status = 'READY'
                """,
                {"team_id": team_id},
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return ImageRecord(
            data=bytes(row["image_data"]),
            content_type=row["content_type"],
            content_sha256=row["content_sha256"],
        )


def _team(row: dict, side: str) -> FixtureTeamRecord:
    return FixtureTeamRecord(
        team_id=row[f"{side}_team_id"],
        name=row[f"{side}_team_name"],
        short_name=row[f"{side}_short_name"],
        club=row[f"{side}_club"],
        badge_version=row[f"{side}_badge_version"],
    )

