"""Football season arithmetic, matching the worker's `app.seasons`.

A season is named by the year it starts in (2026 is 2026-27); 0 means the season in progress.
"""

from __future__ import annotations

from datetime import UTC, datetime

SEASON_START_MONTH = 7
CURRENT_SEASON = 0


def current_season(now: datetime | None = None) -> int:
    moment = now or datetime.now(UTC)
    return moment.year if moment.month >= SEASON_START_MONTH else moment.year - 1


def describe_season(configured: int) -> str:
    if configured:
        return f"{configured}-{(configured + 1) % 100:02d}"
    season = current_season()
    return f"current ({season}-{(season + 1) % 100:02d})"
