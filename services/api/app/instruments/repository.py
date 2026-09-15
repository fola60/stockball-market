from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from typing import Iterator, Protocol
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.common.decimal import format_decimal
from app.database import connection as pooled_connection
from app.instruments.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
    PlayerStatsRecord,
    PriceSnapshotReason,
    PriceSnapshotRecord,
    RadarAxisRecord,
)


class InstrumentsRepository(Protocol):
    def list_instruments(self) -> list[InstrumentRecord]: ...

    def get_instrument(self, instrument_id: UUID) -> InstrumentRecord | None: ...

    def list_price_history(self, instrument_id: UUID) -> list[PriceSnapshotRecord]: ...

    def get_player_stats(self, instrument_id: UUID) -> PlayerStatsRecord | None: ...


class PostgresInstrumentsRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg2.extensions.connection]:
        with pooled_connection(self._database_url) as connection:
            yield connection

    def list_instruments(self) -> list[InstrumentRecord]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        i.id,
                        i.instrument_type,
                        i.player_id,
                        i.symbol,
                        i.display_name,
                        i.current_price,
                        i.shares_outstanding AS quantity_outstanding,
                        i.price_impact_unit,
                        i.trading_status AS status,
                        i.created_at,
                        i.updated_at,
                        p.display_name AS player_name,
                        p.club AS player_club,
                        p.position AS player_position,
                        COALESCE(
                            ROUND(
                                ((i.current_price - opening.opening_price)
                                    / NULLIF(opening.opening_price, 0)) * 100,
                                4
                            ),
                            0
                        ) AS price_change_24h,
                        COALESCE(activity.volume_24h, 0) AS volume_24h
                    FROM instruments AS i
                    JOIN players AS p ON p.id = i.player_id
                    LEFT JOIN LATERAL (
                        SELECT ps.old_price AS opening_price
                        FROM price_snapshots AS ps
                        WHERE ps.instrument_id = i.id
                          AND ps.captured_at >= now() - interval '24 hours'
                        ORDER BY ps.captured_at ASC, ps.id ASC
                        LIMIT 1
                    ) AS opening ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT SUM(t.shares) AS volume_24h
                        FROM trades AS t
                        WHERE t.instrument_id = i.id
                          AND t.executed_at >= now() - interval '24 hours'
                    ) AS activity ON TRUE
                    ORDER BY i.created_at DESC, i.id DESC
                    """
                )
                rows = cursor.fetchall()

        return [_build_instrument_record(row) for row in rows]

    def get_instrument(self, instrument_id: UUID) -> InstrumentRecord | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        i.id,
                        i.instrument_type,
                        i.player_id,
                        i.symbol,
                        i.display_name,
                        i.current_price,
                        i.shares_outstanding AS quantity_outstanding,
                        i.price_impact_unit,
                        i.trading_status AS status,
                        i.created_at,
                        i.updated_at,
                        p.display_name AS player_name,
                        p.club AS player_club,
                        p.position AS player_position,
                        COALESCE(
                            ROUND(
                                ((i.current_price - opening.opening_price)
                                    / NULLIF(opening.opening_price, 0)) * 100,
                                4
                            ),
                            0
                        ) AS price_change_24h,
                        COALESCE(activity.volume_24h, 0) AS volume_24h
                    FROM instruments AS i
                    JOIN players AS p ON p.id = i.player_id
                    LEFT JOIN LATERAL (
                        SELECT ps.old_price AS opening_price
                        FROM price_snapshots AS ps
                        WHERE ps.instrument_id = i.id
                          AND ps.captured_at >= now() - interval '24 hours'
                        ORDER BY ps.captured_at ASC, ps.id ASC
                        LIMIT 1
                    ) AS opening ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT SUM(t.shares) AS volume_24h
                        FROM trades AS t
                        WHERE t.instrument_id = i.id
                          AND t.executed_at >= now() - interval '24 hours'
                    ) AS activity ON TRUE
                    WHERE i.id = %(instrument_id)s
                    """,
                    {"instrument_id": str(instrument_id)},
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return _build_instrument_record(row)

    def list_price_history(self, instrument_id: UUID) -> list[PriceSnapshotRecord]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        instrument_id,
                        old_price,
                        new_price,
                        reason,
                        trade_id,
                        captured_at
                    FROM price_snapshots
                    WHERE instrument_id = %(instrument_id)s
                    ORDER BY captured_at DESC, id DESC
                    """,
                    {"instrument_id": str(instrument_id)},
                )
                rows = cursor.fetchall()

        return [_build_price_snapshot_record(row) for row in rows]

    def get_player_stats(self, instrument_id: UUID) -> PlayerStatsRecord | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    WITH latest AS (
                        SELECT DISTINCT ON (
                            observation.player_id,
                            split_part(observation.provider_fixture_id, ':', 3)
                        )
                            observation.player_id,
                            split_part(observation.provider_fixture_id, ':', 2)::integer AS season,
                            split_part(observation.provider_fixture_id, ':', 3) AS category,
                            observation.stats
                        FROM player_stat_observations AS observation
                        WHERE observation.provider = 'FBREF'
                          AND observation.player_id IS NOT NULL
                        ORDER BY
                            observation.player_id,
                            split_part(observation.provider_fixture_id, ':', 3),
                            observation.observed_at DESC,
                            observation.id DESC
                    ),
                    profiles AS (
                        SELECT
                            player.id AS player_id,
                            split_part(player.position, ',', 1) AS comparison_group,
                            MAX(latest.season) AS season,
                            COALESCE(MAX((latest.stats ->> 'games')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS games,
                            COALESCE(MAX((latest.stats ->> 'games_starts')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS starts,
                            COALESCE(MAX((latest.stats ->> 'minutes')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS minutes,
                            COALESCE(MAX((latest.stats ->> 'goals')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS goals,
                            COALESCE(MAX((latest.stats ->> 'assists')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS assists,
                            COALESCE(MAX((latest.stats ->> 'cards_yellow')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS yellow_cards,
                            COALESCE(MAX((latest.stats ->> 'cards_red')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS red_cards,
                            COALESCE(MAX((latest.stats ->> 'goals_pens_per90')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS goals_per90,
                            COALESCE(MAX((latest.stats ->> 'assists_per90')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS assists_per90,
                            COALESCE(MAX((latest.stats ->> 'shots')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS shots,
                            COALESCE(MAX((latest.stats ->> 'shots_on_target')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS shots_on_target,
                            COALESCE(MAX((latest.stats ->> 'shots_per90')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS shots_per90,
                            COALESCE(MAX((latest.stats ->> 'goals_per_shot')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS goals_per_shot,
                            COALESCE(MAX((latest.stats ->> 'tackles_won')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS tackles_won,
                            COALESCE(MAX((latest.stats ->> 'interceptions')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS interceptions,
                            COALESCE(MAX((latest.stats ->> 'minutes_90s')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS defense_90s,
                            COALESCE(MAX((latest.stats ->> 'gk_save_pct')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS save_pct,
                            COALESCE(MAX((latest.stats ->> 'gk_clean_sheets_pct')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS clean_sheet_pct,
                            COALESCE(MAX((latest.stats ->> 'gk_pens_save_pct')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS penalty_save_pct,
                            COALESCE(MAX((latest.stats ->> 'gk_saves')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS saves,
                            COALESCE(MAX((latest.stats ->> 'gk_wins')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS wins,
                            COALESCE(MAX((latest.stats ->> 'gk_games')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS keeper_games,
                            COALESCE(MAX((latest.stats ->> 'minutes_90s')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS keeper_90s
                        FROM players AS player
                        JOIN latest ON latest.player_id = player.id
                        GROUP BY player.id, split_part(player.position, ',', 1)
                    ),
                    ranked AS (
                        SELECT
                            profiles.*,
                            COUNT(*) OVER (PARTITION BY comparison_group) AS comparison_size,
                            CUME_DIST() OVER (PARTITION BY comparison_group ORDER BY goals_per90) AS goal_score,
                            CUME_DIST() OVER (PARTITION BY comparison_group ORDER BY goals_per_shot) AS finishing_score,
                            CUME_DIST() OVER (PARTITION BY comparison_group ORDER BY shots_per90) AS shot_score,
                            CUME_DIST() OVER (PARTITION BY comparison_group ORDER BY assists_per90) AS creation_score,
                            CUME_DIST() OVER (
                                PARTITION BY comparison_group
                                ORDER BY (tackles_won + interceptions) / NULLIF(defense_90s, 0)
                            ) AS defending_score,
                            CUME_DIST() OVER (PARTITION BY comparison_group ORDER BY minutes) AS availability_score,
                            CUME_DIST() OVER (PARTITION BY comparison_group ORDER BY save_pct) AS save_score,
                            CUME_DIST() OVER (PARTITION BY comparison_group ORDER BY clean_sheet_pct) AS clean_sheet_score,
                            CUME_DIST() OVER (PARTITION BY comparison_group ORDER BY penalty_save_pct) AS penalty_score,
                            CUME_DIST() OVER (
                                PARTITION BY comparison_group
                                ORDER BY wins / NULLIF(keeper_games, 0)
                            ) AS win_score,
                            CUME_DIST() OVER (
                                PARTITION BY comparison_group
                                ORDER BY saves / NULLIF(keeper_90s, 0)
                            ) AS workload_score
                        FROM profiles
                        WHERE games > 0 OR keeper_games > 0
                    )
                    SELECT ranked.*
                    FROM ranked
                    JOIN instruments AS instrument ON instrument.player_id = ranked.player_id
                    WHERE instrument.id = %(instrument_id)s
                    """,
                    {"instrument_id": str(instrument_id)},
                )
                row = cursor.fetchone()

        if row is None:
            return None

        return _build_player_stats_record(row)


def _build_instrument_record(row: dict) -> InstrumentRecord:
    return InstrumentRecord(
        id=row["id"],
        instrument_type=InstrumentType(row["instrument_type"]),
        player_id=row["player_id"],
        symbol=row["symbol"],
        display_name=row["display_name"],
        current_price=format_decimal(_as_decimal(row["current_price"])),
        quantity_outstanding=format_decimal(_as_decimal(row["quantity_outstanding"])),
        price_impact_unit=format_decimal(_as_decimal(row["price_impact_unit"])),
        status=InstrumentStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        player_name=row["player_name"],
        player_club=row["player_club"],
        player_position=row["player_position"],
        price_change_24h=format_decimal(_as_decimal(row["price_change_24h"])),
        volume_24h=format_decimal(_as_decimal(row["volume_24h"])),
    )


def _build_price_snapshot_record(row: dict) -> PriceSnapshotRecord:
    return PriceSnapshotRecord(
        id=row["id"],
        instrument_id=row["instrument_id"],
        old_price=format_decimal(_as_decimal(row["old_price"])),
        new_price=format_decimal(_as_decimal(row["new_price"])),
        reason=PriceSnapshotReason(row["reason"]),
        trade_id=row["trade_id"],
        captured_at=row["captured_at"],
    )


def _build_player_stats_record(row: dict) -> PlayerStatsRecord:
    is_goalkeeper = row["comparison_group"] == "GK"
    if is_goalkeeper:
        axes = [
            RadarAxisRecord("Save rate", _percentile(row["save_score"]), _percent(row["save_pct"])),
            RadarAxisRecord("Clean sheets", _percentile(row["clean_sheet_score"]), _percent(row["clean_sheet_pct"])),
            RadarAxisRecord("Penalty saves", _percentile(row["penalty_score"]), _percent(row["penalty_save_pct"])),
            RadarAxisRecord("Win rate", _percentile(row["win_score"]), _ratio_percent(row["wins"], row["keeper_games"])),
            RadarAxisRecord("Shot stopping", _percentile(row["workload_score"]), _per90(row["saves"], row["keeper_90s"])),
            RadarAxisRecord("Availability", _percentile(row["availability_score"]), f'{int(row["minutes"])} min'),
        ]
    else:
        axes = [
            RadarAxisRecord("Goal threat", _percentile(row["goal_score"]), f'{_decimal(row["goals_per90"], 2)} /90'),
            RadarAxisRecord("Finishing", _percentile(row["finishing_score"]), f'{_decimal(row["goals_per_shot"], 2)} /shot'),
            RadarAxisRecord("Shot volume", _percentile(row["shot_score"]), f'{_decimal(row["shots_per90"], 2)} /90'),
            RadarAxisRecord("Creation", _percentile(row["creation_score"]), f'{_decimal(row["assists_per90"], 2)} ast /90'),
            RadarAxisRecord("Ball winning", _percentile(row["defending_score"]), _per90(row["tackles_won"] + row["interceptions"], row["defense_90s"])),
            RadarAxisRecord("Availability", _percentile(row["availability_score"]), f'{int(row["minutes"])} min'),
        ]

    return PlayerStatsRecord(
        season=row["season"],
        games=int(row["games"]),
        starts=int(row["starts"]),
        minutes=int(row["minutes"]),
        goals=int(row["goals"]),
        assists=int(row["assists"]),
        shots=int(row["shots"]),
        shots_on_target=int(row["shots_on_target"]),
        yellow_cards=int(row["yellow_cards"]),
        red_cards=int(row["red_cards"]),
        comparison_group=row["comparison_group"],
        comparison_size=int(row["comparison_size"]),
        radar_axes=axes,
    )


def _percentile(value: Decimal | float | None) -> int:
    return max(0, min(100, round(float(value or 0) * 100)))


def _decimal(value: Decimal | float | None, places: int) -> str:
    return f"{float(value or 0):.{places}f}"


def _percent(value: Decimal | float | None) -> str:
    return f"{_decimal(value, 1)}%"


def _ratio_percent(numerator: Decimal, denominator: Decimal) -> str:
    if not denominator:
        return "0.0%"
    return f"{float(numerator / denominator * 100):.1f}%"


def _per90(value: Decimal, nineties: Decimal) -> str:
    if not nineties:
        return "0.00 /90"
    return f"{float(value / nineties):.2f} /90"


def _as_decimal(value: Decimal) -> Decimal:
    return value
