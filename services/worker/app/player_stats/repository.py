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
