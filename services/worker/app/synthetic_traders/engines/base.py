from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from statistics import fmean, pstdev
from typing import Iterable, Protocol, Sequence

from app.clients.trading_engine import OrderSide
from app.synthetic_traders.config import CandidateUniverseConfig, StrategyConfig
from app.synthetic_traders.models import (
    BotTickContext,
    CandidateInstrumentContext,
    DecisionSide,
    MarketTradeSample,
    PlayerStatsContext,
    PricePoint,
    StrategyDecision,
    StrategyEngine,
)
from app.synthetic_traders.ranking import rank_percentiles as rank_percentiles

POSITION_ALIASES = {
    "FW": "FWD",
    "FWD": "FWD",
    "FORWARD": "FWD",
    "MF": "MID",
    "MID": "MID",
    "MIDFIELDER": "MID",
    "DF": "DEF",
    "DEF": "DEF",
    "DEFENDER": "DEF",
    "GK": "GK",
    "GOALKEEPER": "GK",
}


def canonical_position_codes(position: str | None) -> tuple[str, ...]:
    if position is None:
        return ()
    normalized = position.upper().replace("/", ",").replace("|", ",")
    return tuple(
        dict.fromkeys(
            POSITION_ALIASES.get(value, value)
            for item in normalized.split(",")
            if (value := item.strip())
        )
    )


class StrategyEngineImplementation(Protocol):
    strategy_engine: StrategyEngine

    def evaluate(
        self,
        context: BotTickContext,
        config: StrategyConfig,
    ) -> tuple[StrategyDecision, ...]: ...


def filter_candidates(
    candidates: Sequence[CandidateInstrumentContext],
    universe: CandidateUniverseConfig,
    selection_key: str = "",
) -> list[CandidateInstrumentContext]:
    filtered: list[CandidateInstrumentContext] = []

    for candidate in candidates:
        if candidate_exclusion_reason(candidate, universe) is not None:
            continue
        filtered.append(candidate)

    # Reserve half the budget for holdings; use a reproducible rotating sample for discovery.
    filtered.sort(
        key=lambda item: sha256(f"{selection_key}:{item.instrument_id}".encode()).digest()
    )
    held = [item for item in filtered if item.current_holding_quantity > 0]
    reserved = held[: max(1, universe.max_candidates // 2)]
    discovery = [item for item in filtered if item.current_holding_quantity <= 0]
    return (reserved + discovery + held[len(reserved) :])[: universe.max_candidates]


def candidate_exclusion_counts(
    candidates: Sequence[CandidateInstrumentContext],
    universe: CandidateUniverseConfig,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    eligible = 0
    for candidate in candidates:
        reason = candidate_exclusion_reason(candidate, universe)
        if reason is None:
            eligible += 1
            continue
        counts[reason] = counts.get(reason, 0) + 1
    if eligible > universe.max_candidates:
        counts["candidate_limit"] = eligible - universe.max_candidates
    return counts


def candidate_exclusion_reason(
    candidate: CandidateInstrumentContext,
    universe: CandidateUniverseConfig,
) -> str | None:
    included_positions = {
        code
        for position in universe.included_positions
        for code in canonical_position_codes(position)
    }
    excluded_positions = {
        code
        for position in universe.excluded_positions
        for code in canonical_position_codes(position)
    }
    included_clubs = {club.lower() for club in universe.included_clubs}
    excluded_clubs = {club.lower() for club in universe.excluded_clubs}
    if universe.require_active_instrument and candidate.trading_status != "ACTIVE":
        return "inactive_instrument"
    position_codes = set(canonical_position_codes(candidate.position))
    if position_codes and included_positions and position_codes.isdisjoint(included_positions):
        return "position_not_included"
    if position_codes.intersection(excluded_positions):
        return "position_excluded"
    if (
        candidate.club is not None
        and included_clubs
        and candidate.club.lower() not in included_clubs
    ):
        return "club_not_included"
    if candidate.club is not None and candidate.club.lower() in excluded_clubs:
        return "club_excluded"
    if candidate.current_price < universe.min_current_price:
        return "price_below_minimum"
    if (
        universe.max_current_price is not None
        and candidate.current_price > universe.max_current_price
    ):
        return "price_above_maximum"
    if len(candidate.recent_trades) < universe.min_recent_trades:
        return "insufficient_recent_trades"
    if trade_volume_cash(candidate.recent_trades) < universe.min_recent_volume_cash:
        return "insufficient_recent_volume"
    return None


def window_prices(
    prices: Sequence[PricePoint],
    window_start: datetime | None,
) -> list[PricePoint]:
    if window_start is None:
        return list(prices)
    return [point for point in prices if point.captured_at >= window_start]


def window_trades(
    trades: Sequence[MarketTradeSample],
    window_start: datetime | None,
) -> list[MarketTradeSample]:
    if window_start is None:
        return list(trades)
    return [trade for trade in trades if trade.executed_at >= window_start]


def price_change_pct(
    prices: Sequence[PricePoint],
    current_price: Decimal,
    window_start: datetime,
) -> float:
    points = window_prices(prices, window_start)
    if not points:
        return 0.0
    start_price = points[0].price
    if start_price <= 0:
        return 0.0
    return float((current_price - start_price) / start_price)


def breakout_strength(
    prices: Sequence[PricePoint],
    current_price: Decimal,
    window_start: datetime,
) -> float:
    points = window_prices(prices, window_start)
    if not points:
        return 0.0
    historical = points[:-1] if len(points) > 1 and points[-1].price == current_price else points
    historical_high = max(point.price for point in historical)
    if historical_high <= 0:
        return 0.0
    return float((current_price - historical_high) / historical_high)


def volatility_pct(
    prices: Sequence[PricePoint],
    window_start: datetime,
) -> float:
    bars = {}
    for point in sorted(window_prices(prices, window_start), key=lambda p: p.captured_at):
        bars[point.captured_at.replace(minute=0, second=0, microsecond=0)] = point
    points = list(bars.values())
    if len(points) < 2:
        return 0.0
    returns: list[float] = []
    previous = points[0].price
    for point in points[1:]:
        if previous > 0:
            returns.append(float((point.price - previous) / previous))
        previous = point.price
    if len(returns) < 2:
        return abs(returns[0]) if returns else 0.0
    return pstdev(returns)


def buy_sell_pressure(trades: Sequence[MarketTradeSample]) -> float:
    buy_cash = trade_volume_cash(trade for trade in trades if trade.side is OrderSide.BUY)
    sell_cash = trade_volume_cash(trade for trade in trades if trade.side is OrderSide.SELL)
    total = buy_cash + sell_cash
    if total <= 0:
        return 0.0
    return float((buy_cash - sell_cash) / total)


def trade_volume_cash(trades: Iterable[MarketTradeSample]) -> Decimal:
    total = Decimal("0")
    for trade in trades:
        total += trade.gross_amount
    return total


def unique_trader_count(trades: Sequence[MarketTradeSample]) -> int:
    return len({trade.account_id for trade in trades})


def decide_alpha_side(
    alpha_score: float,
    confidence: float,
    *,
    buy_threshold: float,
    sell_threshold: float,
    min_confidence: float,
    allow_sells: bool,
) -> DecisionSide:
    if confidence < min_confidence:
        return DecisionSide.HOLD
    if alpha_score >= buy_threshold:
        return DecisionSide.BUY
    if allow_sells and alpha_score <= sell_threshold:
        return DecisionSide.SELL
    return DecisionSide.HOLD


def sorted_decisions(decisions: Iterable[StrategyDecision]) -> tuple[StrategyDecision, ...]:
    return tuple(
        sorted(
            decisions,
            key=lambda decision: (decision.side is not DecisionSide.HOLD, decision.priority_score),
            reverse=True,
        )
    )


def average(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return fmean(values)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def positive_score(value: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    return clamp(value / scale, -1.0, 1.0)


# Season ratings of Premier League regulars in 2025-26 FotMob data: median about 6.95, with
# 6.49 and 7.38 at the 5th and 95th percentiles. Used only when no league percentile is known.
TYPICAL_SEASON_RATING = 6.95
SEASON_RATING_SPREAD = 0.45


def rating_score(stats: PlayerStatsContext) -> float | None:
    """-1..1: how well the player rates against the league, or None without ratings.

    Prefers the league percentile; a lone rating is placed on the regulars' distribution, since
    a linear 0-10 scale would squeeze nearly every season rating into a narrow band.
    """
    if stats.rating_strength is not None:
        return clamp(stats.rating_strength, -1.0, 1.0)
    if stats.average_rating is not None:
        return clamp(
            (stats.average_rating - TYPICAL_SEASON_RATING) / SEASON_RATING_SPREAD, -1.0, 1.0
        )
    return None


def stats_confirmation(stats: PlayerStatsContext) -> float:
    """-1..1: how strong a player's stats look, averaging the league percentiles on per-90
    contribution and on match rating that are available. A rating complements the per-90
    view rather than replacing it, so players with and without ratings share one scale."""
    scores = [
        score
        for score in (
            None if stats.strength is None else clamp(stats.strength, -1.0, 1.0),
            rating_score(stats),
        )
        if score is not None
    ]
    return fmean(scores) if scores else 0.0
