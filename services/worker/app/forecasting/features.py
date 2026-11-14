"""Turn a player's match history into what was knowable at one moment, and what happened next.

Every feature is computed from matches that kicked off before the as-of time, so a training
row never sees its own future. The target is the player's minutes-weighted FotMob rating over
his next `horizon` rated appearances, and the model learns how far that lands from the
steadied season rating the stats bots already price (`app.player_stats.ratings`).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import log10
from statistics import fmean, median, pstdev
from typing import Iterable, Mapping, Sequence

from app.player_stats.ratings import (
    MIN_PRIOR_RATED_NINETIES,
    RATING_PRIOR_NINETIES,
    RatingTotals,
    build_rating_profile,
    rating_prior,
)

HORIZONS: tuple[int, ...] = (1, 5, 10)
# A player needs this much rated football, this season and last, before he is forecast.
MIN_HISTORY_NINETIES = 2.0
# Target appearances further away than this are another spell, not "what happens next".
MAX_TARGET_GAP_DAYS = 200
# The target must cover at least this share of `horizon` full matches; cameos rate near 6.3
# almost regardless, so a target made of them says nothing.
MIN_TARGET_NINETIES_SHARE = 0.5
TEAM_FORM_MATCHES = 10
# A team's recent odds are steadied toward an even match with this many matches of evidence.
TEAM_PRIOR_MATCHES = 3.0
FALLBACK_LEAGUE_RATING = 6.9

POSITION_NAMES = {0: "pos_gk", 1: "pos_def", 2: "pos_mid", 3: "pos_fwd"}

FEATURE_NAMES: tuple[str, ...] = (
    "baseline_vs_league",
    "season_nineties",
    "prior_weight",
    "prev_season_gap",
    "prev_season_nineties",
    "career_gap",
    "career_nineties",
    "last1_gap",
    "last3_gap",
    "last5_gap",
    "last10_gap",
    "rating_sd10",
    "minutes_last5",
    "start_share5",
    "team_match_share5",
    "layoff_days",
    "pos_gk",
    "pos_def",
    "pos_mid",
    "pos_fwd",
    "age",
    "age_sq",
    "goal_involvements_per90",
    "expected_involvements_per90",
    "chances_created_per90",
    "defensive_actions_per90",
    "team_strength",
    "team_goal_difference",
    "next_opponent_strength",
    "next_home_share",
    "value_log",
    "value_change_12m",
)


@dataclass(frozen=True)
class Appearance:
    provider_player_id: str
    player_id: str | None
    match_id: str
    season: int
    kickoff_at: datetime
    team_id: str
    rating: float | None
    minutes: int
    position: int | None = None
    goals: float = 0.0
    assists: float = 0.0
    expected_goals: float = 0.0
    expected_assists: float = 0.0
    chances_created: float = 0.0
    defensive_actions: float = 0.0

    @property
    def nineties(self) -> float:
        return min(self.minutes, 90) / 90.0

    @property
    def rated(self) -> bool:
        return self.rating is not None and self.minutes > 0


@dataclass(frozen=True)
class Fixture:
    match_id: str
    season: int
    kickoff_at: datetime
    home_team_id: str
    away_team_id: str
    finished: bool
    home_goals: int | None = None
    away_goals: int | None = None
    # Bookmakers' pre-match home-win probability minus away-win probability, margin removed.
    home_edge: float | None = None


@dataclass(frozen=True)
class Target:
    """What happened over the next `horizon` rated appearances: how far their rating landed
    from the baseline, the weight that evidence deserves (share of `horizon` full matches),
    and when the last of them kicked off, which is when this outcome became known."""

    change: float
    weight: float
    matured_at: datetime


@dataclass(frozen=True)
class FeatureRow:
    """One player at one moment. `targets` is empty for a live row, whose future has not
    happened."""

    provider_player_id: str
    player_id: str | None
    season: int
    as_of: datetime
    baseline: float
    history_nineties: float
    features: Mapping[int, Mapping[str, float | None]]
    targets: Mapping[int, Target]


class LeagueContext:
    """Team strength and fixture lists, looked up as of any moment.

    A team's strength is how heavily bookmakers favoured it in its recent matches. In testing
    this predicted players' ratings about twice as well as the team's own recent ratings, so
    those are not used.
    """

    def __init__(self, fixtures: Iterable[Fixture]) -> None:
        def edge(fixture: Fixture, team_id: str) -> float | None:
            if fixture.home_edge is None:
                return None
            return fixture.home_edge if fixture.home_team_id == team_id else -fixture.home_edge

        by_team: dict[str, list[tuple[datetime, Fixture]]] = {}
        for fixture in fixtures:
            for team_id in (fixture.home_team_id, fixture.away_team_id):
                by_team.setdefault(team_id, []).append((fixture.kickoff_at, fixture))
        self._kickoffs: dict[str, list[datetime]] = {}
        self._fixtures: dict[str, list[Fixture]] = {}
        self._played: dict[str, list[tuple[datetime, float | None, float | None]]] = {}
        for team_id, items in by_team.items():
            items.sort(key=lambda item: (item[0], item[1].match_id))
            self._kickoffs[team_id] = [kickoff for kickoff, _ in items]
            self._fixtures[team_id] = [fixture for _, fixture in items]
            self._played[team_id] = [
                (
                    fixture.kickoff_at,
                    edge(fixture, team_id),
                    _goal_difference(fixture, team_id),
                )
                for _, fixture in items
                if fixture.finished
            ]
        self._played_kickoffs = {
            team_id: [kickoff for kickoff, _, _ in played]
            for team_id, played in self._played.items()
        }

    def recent_matches(
        self, team_id: str, as_of: datetime, count: int
    ) -> list[tuple[datetime, float | None, float | None]]:
        played = self._played.get(team_id, [])
        end = bisect_right(self._played_kickoffs.get(team_id, []), as_of)
        return played[max(end - count, 0) : end]

    def strength(self, team_id: str, as_of: datetime) -> float | None:
        """The bookmakers' average edge for the team over its recent matches, steadied toward
        zero (an even match). None when none of those matches has odds on record."""
        edges = [
            edge
            for _, edge, _ in self.recent_matches(team_id, as_of, TEAM_FORM_MATCHES)
            if edge is not None
        ]
        return sum(edges) / (len(edges) + TEAM_PRIOR_MATCHES) if edges else None

    def goal_difference(self, team_id: str, as_of: datetime) -> float:
        differences = [
            difference
            for _, _, difference in self.recent_matches(team_id, as_of, TEAM_FORM_MATCHES)
            if difference is not None
        ]
        return sum(differences) / (len(differences) + TEAM_PRIOR_MATCHES)

    def upcoming(self, team_id: str, as_of: datetime, count: int) -> list[Fixture]:
        start = bisect_right(self._kickoffs.get(team_id, []), as_of)
        return self._fixtures.get(team_id, [])[start : start + count]

    def matches_between(self, team_id: str, start: datetime, end: datetime) -> int:
        kickoffs = self._played_kickoffs.get(team_id, [])
        return bisect_right(kickoffs, end) - bisect_left(kickoffs, start)


def league_ratings(appearances: Iterable[Appearance]) -> dict[int, float]:
    """The typical regular's rating for each season, taken from the season before it, as the
    live rating profiles do. The first season on record has no predecessor and uses a fixed
    typical value: its own median is not known until it ends."""
    totals: dict[int, dict[str, list[float]]] = {}
    for item in appearances:
        if item.rated:
            entry = totals.setdefault(item.season, {}).setdefault(
                item.provider_player_id, [0.0, 0.0]
            )
            entry[0] += float(item.rating or 0.0) * item.nineties
            entry[1] += item.nineties
    medians = {
        season: median(means)
        for season, players in totals.items()
        if (
            means := [
                weighted / nineties
                for weighted, nineties in players.values()
                if nineties >= MIN_PRIOR_RATED_NINETIES
            ]
        )
    }
    if not totals:
        return {}
    # One season past the data, for a live row early in a season with no ratings yet.
    seasons = [*totals, max(totals) + 1]
    return {season: medians.get(season - 1, FALLBACK_LEAGUE_RATING) for season in seasons}


def build_rows(
    appearances: Sequence[Appearance],
    fixtures: Sequence[Fixture],
    *,
    birth_dates: Mapping[str, date] | None = None,
    market_values: Mapping[str, Sequence[tuple[date, float]]] | None = None,
    live_as_of: datetime | None = None,
    live_season: int | None = None,
) -> list[FeatureRow]:
    """Training rows (one per appearance, with whichever targets have matured), or with
    `live_as_of` one row per player describing him now, with no targets.

    `birth_dates` is keyed by provider player id and `market_values` by canonical player id.
    A player without one sits at the average for that feature. There is deliberately no
    "missing" indicator: market values exist only for players on today's roster, so in older
    seasons such a flag would mark who went on to stay in the league.
    """
    context = LeagueContext(fixtures)
    leagues = league_ratings(appearances)
    by_player: dict[str, list[Appearance]] = {}
    for item in appearances:
        if item.minutes > 0:
            by_player.setdefault(item.provider_player_id, []).append(item)

    rows: list[FeatureRow] = []
    for history in by_player.values():
        history.sort(key=lambda item: (item.kickoff_at, item.match_id))
        player_id = next((item.player_id for item in reversed(history) if item.player_id), None)
        birth_date = (birth_dates or {}).get(history[0].provider_player_id)
        values = (market_values or {}).get(player_id or "", ())
        if live_as_of is not None:
            past = [item for item in history if item.kickoff_at <= live_as_of]
            if not past:
                continue
            season = live_season if live_season is not None else past[-1].season
            row = _row(
                past, len(past) - 1, season, live_as_of, context, leagues, birth_date, values
            )
            if row is not None:
                rows.append(row)
            continue
        for index, item in enumerate(history):
            row = _row(
                history, index, item.season, item.kickoff_at, context, leagues, birth_date, values
            )
            if row is None:
                continue
            targets = _targets(history, index, row.baseline)
            if targets:
                rows.append(
                    FeatureRow(
                        provider_player_id=row.provider_player_id,
                        player_id=row.player_id,
                        season=row.season,
                        as_of=row.as_of,
                        baseline=row.baseline,
                        history_nineties=row.history_nineties,
                        features=row.features,
                        targets=targets,
                    )
                )
    return rows


def _row(
    history: Sequence[Appearance],
    index: int,
    season: int,
    as_of: datetime,
    context: LeagueContext,
    leagues: Mapping[int, float],
    birth_date: date | None,
    values: Sequence[tuple[date, float]],
) -> FeatureRow | None:
    past = history[: index + 1]
    latest = past[-1]
    rated = [item for item in past if item.rated]
    league = leagues.get(season, FALLBACK_LEAGUE_RATING)

    current = _totals(item for item in rated if item.season == season)
    previous = _totals(item for item in rated if item.season == season - 1)
    if current.nineties + previous.nineties < MIN_HISTORY_NINETIES:
        return None
    earlier = _totals(item for item in rated if item.season < season)
    profile = build_rating_profile(
        season, current, rating_prior(previous if previous.nineties else None, league)
    )
    baseline = profile.rating

    def gap(count: int) -> float:
        recent = rated[-count:]
        nineties = sum(item.nineties for item in recent)
        if nineties <= 0:
            return 0.0
        mean = sum(float(item.rating or 0.0) * item.nineties for item in recent) / nineties
        # A handful of minutes is weak evidence, so the gap counts in proportion to them.
        return (mean - baseline) * min(nineties / count, 1.0)

    last_ratings = [float(item.rating or 0.0) for item in rated[-10:]]
    last5 = past[-5:]
    window = past[-10:]
    window_nineties = sum(item.nineties for item in window)

    def per90(total: float) -> float:
        return total / window_nineties if window_nineties > 0 else 0.0

    team_recent = context.recent_matches(latest.team_id, as_of, 5)
    team_share = (
        sum(1 for item in past[-8:] if item.kickoff_at >= team_recent[0][0]) / len(team_recent)
        if team_recent
        else None
    )
    age = (as_of.date() - birth_date).days / 365.25 if birth_date else None
    value_now = _value_on(values, as_of.date())
    value_before = _value_on(values, as_of.date() - timedelta(days=365))

    shared: dict[str, float | None] = {
        "baseline_vs_league": baseline - league,
        "season_nineties": current.nineties,
        "prior_weight": profile.prior_weight,
        "prev_season_gap": (previous.mean or league) - league,
        "prev_season_nineties": previous.nineties,
        "career_gap": (earlier.weighted_sum - league * earlier.nineties)
        / (earlier.nineties + RATING_PRIOR_NINETIES),
        "career_nineties": earlier.nineties,
        "last1_gap": gap(1),
        "last3_gap": gap(3),
        "last5_gap": gap(5),
        "last10_gap": gap(10),
        "rating_sd10": pstdev(last_ratings) if len(last_ratings) >= 3 else None,
        "minutes_last5": fmean(item.minutes for item in last5) / 90.0,
        "start_share5": sum(1 for item in last5 if item.minutes >= 60) / len(last5),
        "team_match_share5": None if team_share is None else min(team_share, 1.0),
        "layoff_days": (
            min((latest.kickoff_at - past[-2].kickoff_at).days, 120.0) if len(past) > 1 else None
        ),
        **{name: float(latest.position == code) for code, name in POSITION_NAMES.items()},
        "age": age,
        "age_sq": None if age is None else (age - 26.0) ** 2,
        "goal_involvements_per90": per90(sum(item.goals + item.assists for item in window)),
        "expected_involvements_per90": per90(
            sum(item.expected_goals + item.expected_assists for item in window)
        ),
        "chances_created_per90": per90(sum(item.chances_created for item in window)),
        "defensive_actions_per90": per90(sum(item.defensive_actions for item in window)),
        "team_strength": context.strength(latest.team_id, as_of),
        "team_goal_difference": context.goal_difference(latest.team_id, as_of),
        "value_log": None if value_now is None else _log10(value_now),
        "value_change_12m": (
            None
            if value_now is None or value_before is None
            else _log10(value_now) - _log10(value_before)
        ),
    }
    features: dict[int, Mapping[str, float | None]] = {}
    for horizon in HORIZONS:
        upcoming = context.upcoming(latest.team_id, as_of, horizon)
        opponents = [
            strength
            for fixture in upcoming
            if (
                strength := context.strength(
                    fixture.away_team_id
                    if fixture.home_team_id == latest.team_id
                    else fixture.home_team_id,
                    as_of,
                )
            )
            is not None
        ]
        features[horizon] = {
            **shared,
            "next_opponent_strength": fmean(opponents) if opponents else None,
            "next_home_share": (
                sum(1 for fixture in upcoming if fixture.home_team_id == latest.team_id)
                / len(upcoming)
                if upcoming
                else None
            ),
        }
    return FeatureRow(
        provider_player_id=latest.provider_player_id,
        player_id=next((item.player_id for item in reversed(past) if item.player_id), None),
        season=season,
        as_of=as_of,
        baseline=baseline,
        history_nineties=current.nineties + previous.nineties,
        features=features,
        targets={},
    )


def _targets(
    history: Sequence[Appearance], index: int, baseline: float
) -> dict[int, Target]:
    """The outcome for each horizon with enough football after `index`."""
    cutoff = history[index].kickoff_at + timedelta(days=MAX_TARGET_GAP_DAYS)
    future = [item for item in history[index + 1 :] if item.rated and item.kickoff_at <= cutoff]
    targets: dict[int, Target] = {}
    for horizon in HORIZONS:
        window = future[:horizon]
        nineties = sum(item.nineties for item in window)
        if len(window) < horizon or nineties < MIN_TARGET_NINETIES_SHARE * horizon:
            continue
        mean = sum(float(item.rating or 0.0) * item.nineties for item in window) / nineties
        targets[horizon] = Target(
            change=mean - baseline,
            weight=min(nineties / horizon, 1.0),
            matured_at=window[-1].kickoff_at,
        )
    return targets


def _totals(items: Iterable[Appearance]) -> RatingTotals:
    weighted = nineties = 0.0
    for item in items:
        weighted += float(item.rating or 0.0) * item.nineties
        nineties += item.nineties
    return RatingTotals(weighted_sum=weighted, nineties=nineties)


def _goal_difference(fixture: Fixture, team_id: str) -> float | None:
    if fixture.home_goals is None or fixture.away_goals is None:
        return None
    difference = float(fixture.home_goals - fixture.away_goals)
    return difference if fixture.home_team_id == team_id else -difference


def _value_on(values: Sequence[tuple[date, float]], on: date) -> float | None:
    """The latest published value on or before `on`; values are sorted by date."""
    index = bisect_right(values, (on, float("inf")))
    return values[index - 1][1] if index else None


def _log10(value: float) -> float:
    return log10(max(value, 1.0))
