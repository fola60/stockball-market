"""Player profiles: per-90 output from FBref season-total snapshots and match ratings from FotMob.

FBref publishes season-to-date tables, one per stat family. Everything that reasons about a
player's quality (synthetic traders, seed pricing) reads them through this package, so totals
are combined across tables and clubs, turned into per-90 rates, steadied early in a season
with the previous season, and compared between snapshots for recent form. FotMob match ratings
are minutes-weighted and steadied the same way (see `ratings`).
"""

from .profiles import (
    PlayerStatProfile,
    SeasonTotals,
    build_profile,
    league_median_rates,
    per90_rates,
    stats_value,
)
from .ratings import (
    MATCH_RATING_SD,
    RATING_PRIOR_NINETIES,
    PlayerRatingProfile,
    RatingTotals,
    build_rating_profile,
    build_rating_profiles,
    league_median_rating,
    rating_prior,
)
from .repository import load_rating_profiles, load_rating_totals, load_stat_profiles

__all__ = [
    "MATCH_RATING_SD",
    "RATING_PRIOR_NINETIES",
    "PlayerRatingProfile",
    "PlayerStatProfile",
    "RatingTotals",
    "SeasonTotals",
    "build_profile",
    "build_rating_profile",
    "build_rating_profiles",
    "league_median_rating",
    "league_median_rates",
    "load_rating_profiles",
    "load_rating_totals",
    "load_stat_profiles",
    "per90_rates",
    "rating_prior",
    "stats_value",
]
