from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

# A season's per-90 rates are blended with a prior (the player's previous season, or the
# league median) carrying this many full matches of evidence, so six early-season games
# don't make a player look elite or useless.
PRIOR_STRENGTH_NINETIES = 8.0
# A previous season counts as the player's own prior once it covers this many full matches.
MIN_PRIOR_NINETIES = 5.0
# Recent form needs at least this many full matches between the two snapshots.
MIN_FORM_NINETIES = 2.0

RATE_NAMES = ("goals", "assists", "shots", "key_passes", "defensive_actions", "cards")


def _number(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _table_sum(tables: Mapping[str, Sequence[Mapping[str, Any]]], table: str, *keys: str) -> float:
    """Sum `keys` over a table's rows; a player has one row per club he played for."""
    return sum(_number(row.get(key)) for row in tables.get(table, ()) for key in keys)


@dataclass(frozen=True)
class SeasonTotals:
    available_rates: frozenset[str] | None = None
    observed_at: datetime | None = None
    games: float = 0.0
    starts: float = 0.0
    minutes: float = 0.0
    goals: float = 0.0
    assists: float = 0.0
    shots: float = 0.0
    key_passes: float = 0.0
    defensive_actions: float = 0.0
    defensive_nineties: float = 0.0
    cards: float = 0.0
    clean_sheets: float = 0.0
    keeper_games: float = 0.0

    @property
    def nineties(self) -> float:
        return self.minutes / 90.0

    @classmethod
    def from_tables(cls, tables: Mapping[str, Sequence[Mapping[str, Any]]]) -> "SeasonTotals":
        sources = {
            "goals": ("standard", ("goals",)),
            "assists": ("standard", ("assists",)),
            "shots": ("shooting", ("shots",)),
            "key_passes": ("passing", ("assisted_shots",)),
            "defensive_actions": ("defense", ("tackles_won", "interceptions", "blocks")),
            "cards": ("standard", ("cards_yellow", "cards_red")),
        }
        available = frozenset(
            name
            for name, (table, keys) in sources.items()
            if any(row.get(key) is not None for row in tables.get(table, ()) for key in keys)
        )
        return cls(
            available_rates=available,
            games=_table_sum(tables, "standard", "games"),
            starts=_table_sum(tables, "standard", "games_starts"),
            minutes=_table_sum(tables, "standard", "minutes"),
            goals=_table_sum(tables, "standard", "goals"),
            assists=_table_sum(tables, "standard", "assists"),
            shots=_table_sum(tables, "shooting", "shots"),
            key_passes=_table_sum(tables, "passing", "assisted_shots"),
            defensive_actions=_table_sum(
                tables, "defense", "tackles_won", "interceptions", "blocks"
            ),
            defensive_nineties=_table_sum(tables, "defense", "minutes_90s"),
            cards=_table_sum(tables, "standard", "cards_yellow")
            + 2.0 * _table_sum(tables, "standard", "cards_red"),
            clean_sheets=_table_sum(tables, "keeper", "gk_clean_sheets"),
            keeper_games=_table_sum(tables, "keeper", "gk_games"),
        )

    def since(self, earlier: "SeasonTotals") -> "SeasonTotals":
        """What changed after `earlier` (never negative, in case a table was revised)."""
        return SeasonTotals(
            available_rates=frozenset(
                name for name in RATE_NAMES if self.has_rate(name) and earlier.has_rate(name)
            ),
            observed_at=self.observed_at,
            **{
                item.name: max(getattr(self, item.name) - getattr(earlier, item.name), 0.0)
                for item in fields(self)
                if item.name not in {"available_rates", "observed_at"}
            },
        )

    def has_rate(self, name: str) -> bool:
        return self.available_rates is None or name in self.available_rates

    def total(self, name: str) -> float:
        return float(getattr(self, name))

    def rate_nineties(self, name: str) -> float:
        # Defensive actions come from the defense table, which carries its own 90s played.
        if name == "defensive_actions" and self.defensive_nineties > 0:
            return self.defensive_nineties
        return self.nineties


def per90_rates(totals: SeasonTotals) -> dict[str, float | None]:
    return {
        name: (
            None
            if totals.rate_nineties(name) <= 0 or not totals.has_rate(name)
            else totals.total(name) / totals.rate_nineties(name)
        )
        for name in RATE_NAMES
    }


def league_median_rates(
    seasons: Iterable[SeasonTotals], min_nineties: float = MIN_PRIOR_NINETIES
) -> dict[str, float]:
    """Typical per-90 rates among players with enough minutes, the prior for newcomers."""
    regular = [totals for totals in seasons if totals.nineties >= min_nineties]
    rates: dict[str, float] = {}
    for name in RATE_NAMES:
        values = [
            value
            for value in (per90_rates(totals)[name] for totals in regular)
            if value is not None
        ]
        if values:
            rates[name] = median(values)
    return rates


@dataclass(frozen=True)
class PlayerStatProfile:
    season: int
    games: float
    starts: float
    minutes: float
    minutes_per_game: float | None
    goals_per90: float
    assists_per90: float
    shots_per90: float
    key_passes_per90: float
    defensive_actions_per90: float
    cards_per90: float
    clean_sheets_per_game: float | None
    # Share of each rate that came from the prior rather than this season's matches.
    prior_weight: float
    available_rates: frozenset[str] | None = None
    latest_observed_at: datetime | None = None
    recent_minutes: float = 0.0
    recent_goal_involvements_per90: float | None = None
    recent_defensive_actions_per90: float | None = None


def build_profile(
    season: int,
    current: SeasonTotals,
    prior_rates: Mapping[str, float],
    *,
    prior_minutes_per_game: float | None = None,
    form_base: SeasonTotals | None = None,
) -> PlayerStatProfile:
    def blended(name: str) -> float:
        nineties = current.rate_nineties(name)
        prior = prior_rates.get(name, 0.0)
        if not current.has_rate(name):
            return prior
        if name not in prior_rates:
            return current.total(name) / nineties if nineties > 0 else 0.0
        return (current.total(name) + prior * PRIOR_STRENGTH_NINETIES) / (
            nineties + PRIOR_STRENGTH_NINETIES
        )

    recent = None if form_base is None else current.since(form_base)
    has_form = recent is not None and recent.nineties >= MIN_FORM_NINETIES
    keeper_games = current.keeper_games or (current.games if current.clean_sheets else 0.0)
    return PlayerStatProfile(
        season=season,
        available_rates=frozenset(
            name
            for name in RATE_NAMES
            if (current.has_rate(name) and current.rate_nineties(name) > 0) or name in prior_rates
        ),
        latest_observed_at=current.observed_at,
        games=current.games,
        starts=current.starts,
        minutes=current.minutes,
        minutes_per_game=(
            current.minutes / current.games if current.games > 0 else prior_minutes_per_game
        ),
        goals_per90=blended("goals"),
        assists_per90=blended("assists"),
        shots_per90=blended("shots"),
        key_passes_per90=blended("key_passes"),
        defensive_actions_per90=blended("defensive_actions"),
        cards_per90=blended("cards"),
        clean_sheets_per_game=(current.clean_sheets / keeper_games if keeper_games > 0 else None),
        prior_weight=PRIOR_STRENGTH_NINETIES / (current.nineties + PRIOR_STRENGTH_NINETIES),
        recent_minutes=0.0 if recent is None else recent.minutes,
        recent_goal_involvements_per90=(
            (recent.goals + recent.assists) / recent.nineties
            if has_form
            and recent is not None
            and recent.has_rate("goals")
            and recent.has_rate("assists")
            else None
        ),
        recent_defensive_actions_per90=(
            recent.defensive_actions / recent.rate_nineties("defensive_actions")
            if has_form
            and recent is not None
            and recent.has_rate("defensive_actions")
            and recent.rate_nineties("defensive_actions") > 0
            else None
        ),
    )


def stats_value(profile: PlayerStatProfile) -> float:
    """One number for how much a player contributes, used to rank players for seed pricing.

    Goal involvement dominates, chance creation and defensive work add to it, and a player who
    rarely plays full games is discounted.
    """
    contribution = (
        profile.goals_per90
        + 0.7 * profile.assists_per90
        + 0.15 * profile.key_passes_per90
        + 0.08 * profile.defensive_actions_per90
        + 0.5 * (profile.clean_sheets_per_game or 0.0)
    )
    reliability = min((profile.minutes_per_game or 0.0) / 60.0, 1.0)
    return contribution * reliability
