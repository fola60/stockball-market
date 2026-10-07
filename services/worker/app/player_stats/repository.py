from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Mapping

from .profiles import (
    MIN_PRIOR_NINETIES,
    PlayerStatProfile,
    SeasonTotals,
    build_profile,
    league_median_rates,
    per90_rates,
)
from .ratings import (
    RECENT_RATED_APPEARANCES,
    PlayerRatingProfile,
    RatingTotals,
    build_rating_profiles,
)

# Form compares the latest snapshot with the newest one at least this old.
FORM_WINDOW_DAYS = 21


def load_stat_profiles(cursor: Any, season: int, as_of: date) -> dict[str, PlayerStatProfile]:
    """Profiles for every player with a snapshot this season or last, keyed by player id.

    Works with any DB-API cursor returning mappings (psycopg2 `RealDictCursor`).
    """
    current = _latest_snapshots(cursor, season, as_of)
    previous = _latest_snapshots(cursor, season - 1, as_of)
    form_bases = _latest_snapshots(cursor, season, as_of - timedelta(days=FORM_WINDOW_DAYS))

    # Newcomers are compared with last season's typical regular, or this season's if there
    # is no last season on record.
    league = league_median_rates(previous.values())
    if not any(league.values()):
        league = league_median_rates(current.values())

    profiles: dict[str, PlayerStatProfile] = {}
    for player_id in current.keys() | previous.keys():
        totals = current.get(player_id, SeasonTotals())
        prior_totals = previous.get(player_id)
        if prior_totals is not None and prior_totals.nineties >= MIN_PRIOR_NINETIES:
            prior_rates = {
                name: value if value is not None else league[name]
                for name, value in per90_rates(prior_totals).items()
                if value is not None or name in league
            }
            prior_minutes_per_game = (
                prior_totals.minutes / prior_totals.games if prior_totals.games else None
            )
        else:
            prior_rates = dict(league)
            prior_minutes_per_game = None
        form_base = form_bases.get(player_id)
        profiles[player_id] = build_profile(
            season,
            totals,
            prior_rates,
            prior_minutes_per_game=prior_minutes_per_game,
            # A base equal to the latest snapshot means no newer data yet.
            form_base=form_base if form_base != totals else None,
        )
    return profiles


def load_rating_profiles(
    cursor: Any, season: int, as_of: datetime
) -> dict[str, PlayerRatingProfile]:
    """FotMob rating profiles for every linked player rated this season or last."""
    current, previous = load_rating_totals(cursor, season, as_of)
    return build_rating_profiles(season, current, previous)


def load_rating_totals(
    cursor: Any, season: int, as_of: datetime
) -> tuple[dict[str, RatingTotals], dict[str, RatingTotals]]:
    """Rated minutes for `season` and the one before, from matches kicked off by `as_of`."""
    cursor.execute(
        """
        WITH rated AS (
            SELECT r.player_id::text AS player_id, m.season, m.kickoff_at,
                   r.rating::float8 AS rating, LEAST(r.minutes_played, 90) / 90.0 AS nineties,
                   ROW_NUMBER() OVER (
                       PARTITION BY r.player_id, m.season ORDER BY m.kickoff_at DESC, m.match_id
                   ) AS recency
            FROM player_match_ratings AS r
            JOIN fotmob_matches AS m ON m.match_id = r.provider_match_id
            WHERE r.player_id IS NOT NULL AND r.rating IS NOT NULL AND r.minutes_played > 0
              AND m.season IN (%(season)s, %(season)s - 1) AND m.kickoff_at <= %(as_of)s
        )
        SELECT player_id, season,
               sum(rating * nineties) AS weighted_sum, sum(nineties) AS nineties,
               COALESCE(sum(rating * nineties) FILTER (WHERE recency <= %(recent)s), 0)
                   AS recent_weighted_sum,
               COALESCE(sum(nineties) FILTER (WHERE recency <= %(recent)s), 0) AS recent_nineties,
               max(kickoff_at) AS latest_match_at
        FROM rated
        GROUP BY player_id, season
        """,
        {"season": season, "as_of": as_of, "recent": RECENT_RATED_APPEARANCES},
    )
    totals: dict[int, dict[str, RatingTotals]] = {season: {}, season - 1: {}}
    for row in cursor.fetchall():
        totals[int(row["season"])][str(row["player_id"])] = RatingTotals(
            weighted_sum=float(row["weighted_sum"]),
            nineties=float(row["nineties"]),
            recent_weighted_sum=float(row["recent_weighted_sum"]),
            recent_nineties=float(row["recent_nineties"]),
            latest_match_at=row["latest_match_at"],
        )
    return totals[season], totals[season - 1]


def _latest_snapshots(cursor: Any, season: int, on_or_before: date) -> dict[str, SeasonTotals]:
    cursor.execute(
        """
        SELECT DISTINCT ON (player_id) player_id::text AS player_id, tables, snapshot_date
        FROM player_season_stat_snapshots
        WHERE season = %(season)s AND snapshot_date <= %(on_or_before)s
        ORDER BY player_id, snapshot_date DESC, captured_at DESC, provider
        """,
        {"season": season, "on_or_before": on_or_before},
    )
    return {
        str(row["player_id"]): replace(
            SeasonTotals.from_tables(_tables(row["tables"])),
            observed_at=datetime.combine(row["snapshot_date"], datetime.min.time(), UTC)
            if row.get("snapshot_date")
            else None,
        )
        for row in cursor.fetchall()
    }


def _tables(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
