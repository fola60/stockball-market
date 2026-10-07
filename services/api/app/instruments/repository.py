from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Iterator, Protocol
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from app.common.decimal import format_decimal
from app.database import connection as pooled_connection
from app.instruments.models import (
    ImageRecord,
    InstrumentFreezeRecord,
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
    PlayerStatsRecord,
    PriceSnapshotReason,
    PriceSnapshotRecord,
    RadarAxisRecord,
    RadarMetricRecord,
)


class InstrumentsRepository(Protocol):
    def list_instruments(self) -> list[InstrumentRecord]: ...

    def get_instrument(self, instrument_id: UUID) -> InstrumentRecord | None: ...

    def list_price_history(
        self, instrument_id: UUID, since: datetime | None = None
    ) -> list[PriceSnapshotRecord]: ...

    def get_player_stats(self, instrument_id: UUID) -> PlayerStatsRecord | None: ...

    def get_player_image(self, instrument_id: UUID) -> ImageRecord | None: ...

    def get_club_badge(self, instrument_id: UUID) -> ImageRecord | None: ...


# Joins `portrait` (the player's ready FotMob image) and `badge` (their club's ready
# FotMob logo, through the worker-maintained club mapping) onto `players AS p`. Only
# hashes are read here; image bytes are fetched by the dedicated image queries.
_IMAGE_JOINS = """
    LEFT JOIN (
        SELECT DISTINCT ON (ref.player_id) ref.player_id, image.content_sha256
        FROM player_provider_refs AS ref
        JOIN fotmob_player_images AS image
            ON image.provider_player_id = ref.provider_player_id
           AND image.status = 'READY'
        WHERE ref.provider = 'FOTMOB'
        ORDER BY ref.player_id, ref.is_primary DESC, image.fetched_at DESC
    ) AS portrait ON portrait.player_id = p.id
    LEFT JOIN fotmob_club_teams AS club_team ON club_team.club = p.club
    LEFT JOIN fotmob_team_logos AS badge
        ON badge.provider_team_id = club_team.provider_team_id
       AND badge.status = 'READY'
"""

_IMAGE_VERSIONS = """
    left(portrait.content_sha256, 16) AS player_image_version,
    left(badge.content_sha256, 16) AS club_badge_version
"""


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
                        i.reference_price,
                        i.shares_outstanding AS quantity_outstanding,
                        i.net_shares_purchased,
                        i.full_supply_price_multiplier,
                        i.curve_depth_shares,
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
                        COALESCE(activity.volume_24h, 0) AS volume_24h,
                    """
                    + _IMAGE_VERSIONS
                    + """
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
                    """
                    + _IMAGE_JOINS
                    + """
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
                        i.reference_price,
                        i.shares_outstanding AS quantity_outstanding,
                        i.net_shares_purchased,
                        i.full_supply_price_multiplier,
                        i.curve_depth_shares,
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
                        COALESCE(activity.volume_24h, 0) AS volume_24h,
                        active_freeze.reason AS freeze_reason,
                        active_freeze.started_at AS freeze_started_at,
                        fixture.home_team_name AS freeze_home_team,
                        fixture.away_team_name AS freeze_away_team,
                        fixture.kickoff_at AS freeze_kickoff_at,
                    """
                    + _IMAGE_VERSIONS
                    + """
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
                    LEFT JOIN LATERAL (
                        SELECT f.reason, f.started_at, f.source_key
                        FROM instrument_freezes AS f
                        WHERE f.instrument_id = i.id
                          AND f.released_at IS NULL
                        ORDER BY f.started_at, f.id
                        LIMIT 1
                    ) AS active_freeze ON TRUE
                    LEFT JOIN fixtures AS fixture
                        ON active_freeze.source_key = 'fixture:' || fixture.id::text
                    """
                    + _IMAGE_JOINS
                    + """
                    WHERE i.id = %(instrument_id)s
                    """,
                    {"instrument_id": str(instrument_id)},
                )
                row = cursor.fetchone()

        if row is None:
            return None

        record = _build_instrument_record(row)
        if row["freeze_reason"] is None:
            return record
        return replace(
            record,
            freeze=InstrumentFreezeRecord(
                reason=row["freeze_reason"],
                started_at=row["freeze_started_at"],
                fixture_home_team=row["freeze_home_team"],
                fixture_away_team=row["freeze_away_team"],
                fixture_kickoff_at=row["freeze_kickoff_at"],
            ),
        )

    def get_player_image(self, instrument_id: UUID) -> ImageRecord | None:
        return self._fetch_image(
            """
            SELECT image.image_data, image.content_type, image.content_sha256
            FROM instruments AS i
            JOIN player_provider_refs AS ref
                ON ref.player_id = i.player_id AND ref.provider = 'FOTMOB'
            JOIN fotmob_player_images AS image
                ON image.provider_player_id = ref.provider_player_id
               AND image.status = 'READY'
            WHERE i.id = %(instrument_id)s
            ORDER BY ref.is_primary DESC, image.fetched_at DESC
            LIMIT 1
            """,
            instrument_id,
        )

    def get_club_badge(self, instrument_id: UUID) -> ImageRecord | None:
        return self._fetch_image(
            """
            SELECT badge.image_data, badge.content_type, badge.content_sha256
            FROM instruments AS i
            JOIN players AS p ON p.id = i.player_id
            JOIN fotmob_club_teams AS club_team ON club_team.club = p.club
            JOIN fotmob_team_logos AS badge
                ON badge.provider_team_id = club_team.provider_team_id
               AND badge.status = 'READY'
            WHERE i.id = %(instrument_id)s
            """,
            instrument_id,
        )

    def _fetch_image(self, query: str, instrument_id: UUID) -> ImageRecord | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, {"instrument_id": str(instrument_id)})
                row = cursor.fetchone()

        if row is None:
            return None
        return ImageRecord(
            data=bytes(row["image_data"]),
            content_type=row["content_type"],
            content_sha256=row["content_sha256"],
        )

    def list_price_history(
        self, instrument_id: UUID, since: datetime | None = None
    ) -> list[PriceSnapshotRecord]:
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
                      AND (%(since)s IS NULL OR captured_at >= %(since)s)
                    ORDER BY captured_at DESC, id DESC
                    """,
                    {"instrument_id": str(instrument_id), "since": since},
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
                          -- Only the player's most recent season, so tables never mix seasons.
                          AND split_part(observation.provider_fixture_id, ':', 2)::integer = (
                              SELECT MAX(split_part(other.provider_fixture_id, ':', 2)::integer)
                              FROM player_stat_observations AS other
                              WHERE other.provider = 'FBREF'
                                AND other.player_id = observation.player_id
                          )
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
                            COALESCE(MAX((latest.stats ->> 'goals_assists_per90')::numeric) FILTER (WHERE latest.category = 'standard'), 0) AS goals_assists_per90,
                            COALESCE(MAX((latest.stats ->> 'shots')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS shots,
                            COALESCE(MAX((latest.stats ->> 'shots_on_target')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS shots_on_target,
                            COALESCE(MAX((latest.stats ->> 'shots_per90')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS shots_per90,
                            COALESCE(MAX((latest.stats ->> 'shots_on_target_pct')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS shots_on_target_pct,
                            COALESCE(MAX((latest.stats ->> 'goals_per_shot')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS goals_per_shot,
                            COALESCE(MAX((latest.stats ->> 'goals_per_shot_on_target')::numeric) FILTER (WHERE latest.category = 'shooting'), 0) AS goals_per_shot_on_target,
                            COALESCE(MAX((latest.stats ->> 'passes_completed')::numeric) FILTER (WHERE latest.category = 'passing'), 0) AS passes_completed,
                            COALESCE(MAX((latest.stats ->> 'passes_pct')::numeric) FILTER (WHERE latest.category = 'passing'), 0) AS passes_pct,
                            COALESCE(MAX((latest.stats ->> 'passes_pct_long')::numeric) FILTER (WHERE latest.category = 'passing'), 0) AS passes_pct_long,
                            COALESCE(MAX((latest.stats ->> 'passes_progressive_distance')::numeric) FILTER (WHERE latest.category = 'passing'), 0) AS passes_progressive_distance,
                            COALESCE(MAX((latest.stats ->> 'passes_into_final_third')::numeric) FILTER (WHERE latest.category = 'passing'), 0) AS passes_into_final_third,
                            COALESCE(MAX((latest.stats ->> 'passes_into_penalty_area')::numeric) FILTER (WHERE latest.category = 'passing'), 0) AS passes_into_penalty_area,
                            COALESCE(MAX((latest.stats ->> 'assisted_shots')::numeric) FILTER (WHERE latest.category = 'passing'), 0) AS assisted_shots,
                            COALESCE(MAX((latest.stats ->> 'minutes_90s')::numeric) FILTER (WHERE latest.category = 'passing'), 0) AS passing_90s,
                            COALESCE(MAX((latest.stats ->> 'tackles_won')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS tackles_won,
                            COALESCE(MAX((latest.stats ->> 'interceptions')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS interceptions,
                            COALESCE(MAX((latest.stats ->> 'blocks')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS blocks,
                            COALESCE(MAX((latest.stats ->> 'clearances')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS clearances,
                            COALESCE(MAX((latest.stats ->> 'challenge_tackles_pct')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS challenge_tackles_pct,
                            COALESCE(MAX((latest.stats ->> 'challenges_lost')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS challenges_lost,
                            COALESCE(MAX((latest.stats ->> 'minutes_90s')::numeric) FILTER (WHERE latest.category = 'defense'), 0) AS defense_90s,
                            COALESCE(MAX((latest.stats ->> 'gk_save_pct')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS save_pct,
                            COALESCE(MAX((latest.stats ->> 'gk_clean_sheets_pct')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS clean_sheet_pct,
                            COALESCE(MAX((latest.stats ->> 'gk_clean_sheets')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS clean_sheets,
                            COALESCE(MAX((latest.stats ->> 'gk_pens_save_pct')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS penalty_save_pct,
                            COALESCE(MAX((latest.stats ->> 'gk_pens_saved')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS penalties_saved,
                            COALESCE(MAX((latest.stats ->> 'gk_pens_att')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS penalties_faced,
                            COALESCE(MAX((latest.stats ->> 'gk_saves')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS saves,
                            COALESCE(MAX((latest.stats ->> 'gk_goals_against_per90')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS goals_against_per90,
                            COALESCE(MAX((latest.stats ->> 'gk_wins')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS wins,
                            COALESCE(MAX((latest.stats ->> 'gk_losses')::numeric) FILTER (WHERE latest.category = 'keeper'), 0) AS losses,
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
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY goals_per90) AS goal_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY goals_per_shot) AS finishing_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY goals_per_shot_on_target) AS sot_finishing_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY shots_per90) AS shot_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY shots_on_target_pct) AS shot_accuracy_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY assists_per90) AS creation_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY goals_assists_per90) AS attacking_output_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY passes_completed / GREATEST(passing_90s, 1)) AS pass_volume_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY passes_pct) AS pass_accuracy_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY passes_pct_long) AS long_pass_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY passes_progressive_distance / GREATEST(passing_90s, 1)) AS progression_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY passes_into_final_third / GREATEST(passing_90s, 1)) AS final_third_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY passes_into_penalty_area / GREATEST(passing_90s, 1)) AS box_pass_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY assisted_shots / GREATEST(passing_90s, 1)) AS key_pass_score,
                            PERCENT_RANK() OVER (
                                PARTITION BY comparison_group
                                ORDER BY (tackles_won + interceptions) / GREATEST(defense_90s, 1)
                            ) AS defending_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY blocks / GREATEST(defense_90s, 1)) AS block_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY clearances / GREATEST(defense_90s, 1)) AS clearance_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY tackles_won / GREATEST(defense_90s, 1)) AS tackle_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY interceptions / GREATEST(defense_90s, 1)) AS interception_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY challenge_tackles_pct) AS duel_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY -(challenges_lost / GREATEST(defense_90s, 1))) AS retention_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY minutes) AS availability_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY games) AS games_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY starts / GREATEST(games, 1)) AS start_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY -(yellow_cards / GREATEST(minutes, 1))) AS yellow_card_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY -(red_cards / GREATEST(minutes, 1))) AS red_card_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY save_pct) AS save_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY clean_sheet_pct) AS clean_sheet_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY clean_sheets / GREATEST(keeper_games, 1)) AS clean_sheet_rate_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY penalty_save_pct) AS penalty_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY penalties_saved) AS penalties_saved_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY -goals_against_per90) AS goals_against_score,
                            PERCENT_RANK() OVER (
                                PARTITION BY comparison_group
                                ORDER BY wins / GREATEST(keeper_games, 1)
                            ) AS win_score,
                            PERCENT_RANK() OVER (PARTITION BY comparison_group ORDER BY -(losses / GREATEST(keeper_games, 1))) AS loss_score,
                            PERCENT_RANK() OVER (
                                PARTITION BY comparison_group
                                ORDER BY saves / GREATEST(keeper_90s, 1)
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
        reference_price=format_decimal(_as_decimal(row["reference_price"])),
        quantity_outstanding=format_decimal(_as_decimal(row["quantity_outstanding"])),
        net_shares_purchased=format_decimal(_as_decimal(row["net_shares_purchased"])),
        full_supply_price_multiplier=format_decimal(
            _as_decimal(row["full_supply_price_multiplier"])
        ),
        curve_depth_shares=format_decimal(_as_decimal(row["curve_depth_shares"])),
        status=InstrumentStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        player_name=row["player_name"],
        player_club=row["player_club"],
        player_position=row["player_position"],
        price_change_24h=format_decimal(_as_decimal(row["price_change_24h"])),
        volume_24h=format_decimal(_as_decimal(row["volume_24h"])),
        player_image_version=row["player_image_version"],
        club_badge_version=row["club_badge_version"],
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
    group = row["comparison_group"]
    if group == "GK":
        axes = [
            _axis("Shot stopping", [
                _metric("Save percentage", row["save_score"], _percent(row["save_pct"])),
                _metric("Saves", row["workload_score"], _per90(row["saves"], row["keeper_90s"])),
                _metric("Goals conceded", row["goals_against_score"], f'{_decimal(row["goals_against_per90"], 2)} /90'),
            ]),
            _axis("Clean sheets", [
                _metric("Clean-sheet percentage", row["clean_sheet_score"], _percent(row["clean_sheet_pct"])),
                _metric("Clean sheets", row["clean_sheet_rate_score"], _per_game(row["clean_sheets"], row["keeper_games"])),
                _metric("Goals conceded", row["goals_against_score"], f'{_decimal(row["goals_against_per90"], 2)} /90'),
            ]),
            _axis("Penalty saving", [
                _metric("Penalty save percentage", row["penalty_score"], _percent(row["penalty_save_pct"])),
                _metric("Penalties saved", row["penalties_saved_score"], f'{int(row["penalties_saved"])} of {int(row["penalties_faced"])}'),
            ]),
            _axis("Results", [
                _metric("Win rate", row["win_score"], _ratio_percent(row["wins"], row["keeper_games"])),
                _metric("Loss avoidance", row["loss_score"], _ratio_percent(row["keeper_games"] - row["losses"], row["keeper_games"])),
                _metric("Clean-sheet percentage", row["clean_sheet_score"], _percent(row["clean_sheet_pct"])),
            ]),
            _axis("Discipline", _discipline_metrics(row)),
            _axis("Availability", _availability_metrics(row)),
        ]
    else:
        shooting = _axis("Shooting", [
            _metric("Shots", row["shot_score"], f'{_decimal(row["shots_per90"], 2)} /90'),
            _metric("Shots on target", row["shot_accuracy_score"], _percent(row["shots_on_target_pct"])),
            _metric("Goals", row["goal_score"], f'{_decimal(row["goals_per90"], 2)} /90'),
        ])
        finishing = _axis("Finishing", [
            _metric("Goals per shot", row["finishing_score"], f'{_decimal(row["goals_per_shot"], 2)}'),
            _metric("Goals per shot on target", row["sot_finishing_score"], f'{_decimal(row["goals_per_shot_on_target"], 2)}'),
            _metric("Shot accuracy", row["shot_accuracy_score"], _percent(row["shots_on_target_pct"])),
        ])
        attacking = _axis("Attacking output", [
            _metric("Goals", row["goal_score"], f'{_decimal(row["goals_per90"], 2)} /90'),
            _metric("Assists", row["creation_score"], f'{_decimal(row["assists_per90"], 2)} /90'),
            _metric("Goal contributions", row["attacking_output_score"], f'{_decimal(row["goals_assists_per90"], 2)} /90'),
        ])
        ball_winning = _axis("Ball winning", [
            _metric("Tackles + interceptions", row["defending_score"], _per90(row["tackles_won"] + row["interceptions"], row["defense_90s"])),
            _metric("Tackles won", row["tackle_score"], _per90(row["tackles_won"], row["defense_90s"])),
            _metric("Interceptions", row["interception_score"], _per90(row["interceptions"], row["defense_90s"])),
        ])
        discipline = _axis("Discipline", _discipline_metrics(row))
        availability = _axis("Availability", _availability_metrics(row))

        if group == "DF":
            axes = [ball_winning, attacking, shooting, finishing, discipline, availability]
        elif group == "MF":
            axes = [attacking, shooting, finishing, ball_winning, discipline, availability]
        else:
            axes = [shooting, finishing, attacking, ball_winning, discipline, availability]

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


def _metric(label: str, score: Decimal | float | None, value: str) -> RadarMetricRecord:
    return RadarMetricRecord(label=label, score=_percentile(score), value=value)


def _axis(label: str, components: list[RadarMetricRecord]) -> RadarAxisRecord:
    score = round(sum(component.score for component in components) / len(components))
    return RadarAxisRecord(
        label=label,
        score=score,
        value=f"{len(components)} metrics",
        components=components,
    )


def _discipline_metrics(row: dict) -> list[RadarMetricRecord]:
    return [
        _metric("Yellow cards", row["yellow_card_score"], _per90(row["yellow_cards"], row["minutes"] / 90)),
        _metric("Red cards", row["red_card_score"], _per90(row["red_cards"], row["minutes"] / 90)),
    ]


def _availability_metrics(row: dict) -> list[RadarMetricRecord]:
    return [
        _metric("Minutes played", row["availability_score"], f'{int(row["minutes"])} min'),
        _metric("Start rate", row["start_score"], _ratio_percent(row["starts"], row["games"])),
        _metric("Appearances", row["games_score"], str(int(row["games"]))),
    ]


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


def _per90(value: Decimal, nineties: Decimal, suffix: str = " /90") -> str:
    if not nineties:
        return f"0.00{suffix}"
    return f"{float(value / nineties):.2f}{suffix}"


def _per_game(value: Decimal, games: Decimal) -> str:
    if not games:
        return "0.00 /match"
    return f"{float(value / games):.2f} /match"


def _as_decimal(value: Decimal) -> Decimal:
    return value
