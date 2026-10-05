"""Per-90 player profiles built from FBref season-total snapshots.

FBref publishes season-to-date tables, one per stat family. Everything that reasons about a
player's quality (synthetic traders, seed pricing) reads them through this package, so totals
are combined across tables and clubs, turned into per-90 rates, steadied early in a season
with the previous season, and compared between snapshots for recent form.
"""

from .profiles import (
    PlayerStatProfile,
    SeasonTotals,
    build_profile,
    league_median_rates,
    per90_rates,
    stats_value,
)
from .repository import load_stat_profiles

__all__ = [
    "PlayerStatProfile",
    "SeasonTotals",
    "build_profile",
    "league_median_rates",
    "load_stat_profiles",
    "per90_rates",
    "stats_value",
]
