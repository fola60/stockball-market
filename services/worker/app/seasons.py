"""Football season arithmetic.

A season is named by the year it starts in, so 2026 is the 2026-27 season. Configured seasons
use 0 to mean "the season in progress", which rolls over on its own each summer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

# Premier League seasons end in May and kick off in August; July is the first month that
# belongs to the new season.
SEASON_START_MONTH = 7
CURRENT_SEASON = 0


def season_for(moment: date | datetime) -> int:
    return moment.year if moment.month >= SEASON_START_MONTH else moment.year - 1


def current_season(now: datetime | None = None) -> int:
    return season_for(now or datetime.now(UTC))


def resolve_season(configured: int | None, now: datetime | None = None) -> int:
    """A configured season, or the season in progress when it is 0 or unset."""
    if configured:
        return configured
    return current_season(now)
