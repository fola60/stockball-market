from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from statistics import fmean, pstdev
from typing import Iterable, Mapping, Protocol, Sequence
from uuid import UUID

from app.clients.trading_engine import OrderSide
from app.synthetic_traders.config import CandidateUniverseConfig, StrategyConfig
from app.synthetic_traders.models import (
    BotTickContext,
    CandidateInstrumentContext,
    DecisionSide,
    MarketTradeSample,
    PricePoint,
    StrategyDecision,
    StrategyEngine,
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
) -> list[CandidateInstrumentContext]:
    filtered: list[CandidateInstrumentContext] = []
    included_positions = set(universe.included_positions)
    excluded_positions = set(universe.excluded_positions)
    included_clubs = {club.lower() for club in universe.included_clubs}
    excluded_clubs = {club.lower() for club in universe.excluded_clubs}

    for candidate in candidates:
        if universe.require_active_instrument and candidate.trading_status != "ACTIVE":
            continue
        if candidate.position is not None and included_positions and candidate.position not in included_positions:
            continue
        if candidate.position is not None and candidate.position in excluded_positions:
            continue
        if candidate.club is not None and included_clubs and candidate.club.lower() not in included_clubs:
            continue
        if candidate.club is not None and candidate.club.lower() in excluded_clubs:
            continue
        if candidate.current_price < universe.min_current_price:
            continue
        if universe.max_current_price is not None and candidate.current_price > universe.max_current_price:
            continue
        if len(candidate.recent_trades) < universe.min_recent_trades:
            continue
        if trade_volume_cash(candidate.recent_trades) < universe.min_recent_volume_cash:
            continue
        filtered.append(candidate)

    filtered.sort(
        key=lambda item: (
            item.current_holding_value > 0,
            len(item.recent_trades),
            item.current_holding_value,
            item.current_price,
        ),
        reverse=True,
    )
    return filtered[: universe.max_candidates]


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
    historical_high = max(point.price for point in points)
    if historical_high <= 0:
        return 0.0
    return float((current_price - historical_high) / historical_high)


def volatility_pct(
    prices: Sequence[PricePoint],
    window_start: datetime,
) -> float:
    points = window_prices(prices, window_start)
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


def rank_percentiles(values: Mapping[UUID, float]) -> dict[UUID, float]:
    if not values:
        return {}
    sorted_items = sorted(values.items(), key=lambda item: item[1])
    if len(sorted_items) == 1:
        return {sorted_items[0][0]: 1.0}
    result: dict[UUID, float] = {}
    last_index = len(sorted_items) - 1
    for index, (item_id, _) in enumerate(sorted_items):
        result[item_id] = index / last_index
    return result


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
