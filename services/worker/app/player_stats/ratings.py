from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Iterable, Mapping

# In 2025-26 FotMob data, season ratings of Premier League regulars spread with an SD of about
# 0.28, while one 60+ minute match deviates from the player's own season rating by about 0.77.
# (0.77 / 0.28)^2 ≈ 8, so a season rating is blended with a prior carrying eight full matches
# of evidence, the same strength the per-90 profiles use.
RATING_PRIOR_NINETIES = 8.0
# A previous season counts as the player's own prior once it covers this many rated matches.
MIN_PRIOR_RATED_NINETIES = 5.0
# One match's typical deviation from the player's norm; the unit of a rating surprise.
MATCH_RATING_SD = 0.77
# Rating form compares the latest appearances with the season, once both cover this much.
RECENT_RATED_APPEARANCES = 5
MIN_FORM_RATED_NINETIES = 2.0


@dataclass(frozen=True)
class RatingTotals:
    """A player's rated minutes in one season. Ratings are weighted by nineties played, so a
    ten-minute cameo (which FotMob rates near 6.3 almost regardless) barely counts."""

    weighted_sum: float = 0.0
    nineties: float = 0.0
    recent_weighted_sum: float = 0.0
    recent_nineties: float = 0.0
    latest_match_at: datetime | None = None

    @property
    def mean(self) -> float | None:
        return self.weighted_sum / self.nineties if self.nineties > 0 else None

    def without(self, rating: float, nineties: float) -> RatingTotals:
        """These totals before one appearance, for judging that appearance against them."""
        remaining = max(self.nineties - nineties, 0.0)
        return RatingTotals(
            weighted_sum=self.weighted_sum - rating * nineties if remaining > 0 else 0.0,
            nineties=remaining,
        )


@dataclass(frozen=True)
class PlayerRatingProfile:
    season: int
    # Season rating blended with the prior; what the player is expected to rate next match.
    rating: float
    rated_nineties: float
    # Share of `rating` that came from the prior rather than this season's matches.
    prior_weight: float
    # Latest appearances' rating minus the season's, when both cover enough football.
    form: float | None = None
    latest_match_at: datetime | None = None


def league_median_rating(totals: Iterable[RatingTotals]) -> float | None:
    """The typical regular's rating; newcomers start from it."""
    means = [
        mean
        for item in totals
        if item.nineties >= MIN_PRIOR_RATED_NINETIES and (mean := item.mean) is not None
    ]
    return median(means) if means else None


def rating_prior(previous: RatingTotals | None, league: float) -> float:
    """The player's own last season, itself steadied toward the league, or the league."""
    if previous is None or previous.nineties < MIN_PRIOR_RATED_NINETIES:
        return league
    return (previous.weighted_sum + league * RATING_PRIOR_NINETIES) / (
        previous.nineties + RATING_PRIOR_NINETIES
    )


def build_rating_profile(season: int, current: RatingTotals, prior: float) -> PlayerRatingProfile:
    rating = (current.weighted_sum + prior * RATING_PRIOR_NINETIES) / (
        current.nineties + RATING_PRIOR_NINETIES
    )
    form = None
    season_mean = current.mean
    earlier_nineties = current.nineties - current.recent_nineties
    if (
        season_mean is not None
        and current.recent_nineties >= MIN_FORM_RATED_NINETIES
        and earlier_nineties >= MIN_FORM_RATED_NINETIES
    ):
        form = current.recent_weighted_sum / current.recent_nineties - season_mean
    return PlayerRatingProfile(
        season=season,
        rating=rating,
        rated_nineties=current.nineties,
        prior_weight=RATING_PRIOR_NINETIES / (current.nineties + RATING_PRIOR_NINETIES),
        form=form,
        latest_match_at=current.latest_match_at,
    )


def build_rating_profiles(
    season: int,
    current: Mapping[str, RatingTotals],
    previous: Mapping[str, RatingTotals],
) -> dict[str, PlayerRatingProfile]:
    """Profiles for every player rated this season or last, keyed by player id."""
    league = league_median_rating(previous.values()) or league_median_rating(current.values())
    if league is None:
        return {}
    return {
        player_id: build_rating_profile(
            season,
            current.get(player_id, RatingTotals()),
            rating_prior(previous.get(player_id), league),
        )
        for player_id in current.keys() | previous.keys()
    }
