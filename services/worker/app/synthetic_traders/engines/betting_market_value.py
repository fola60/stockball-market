from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import fmean, median
from typing import Mapping
from uuid import UUID

from app.synthetic_traders.config import BettingMarketValueConfig
from app.synthetic_traders.models import (
    BettingMarketQuote,
    BotTickContext,
    CandidateInstrumentContext,
    DecisionSide,
    StrategyDecision,
    StrategyEngine,
)

from .base import clamp, filter_candidates, rank_percentiles, sorted_decisions


@dataclass(frozen=True)
class _MarketTypeSnapshot:
    probability: float
    movement: float
    observation_depth: float
    latest_observed_at: datetime


@dataclass(frozen=True)
class BettingMarketValueStrategyEngine:
    strategy_engine: StrategyEngine = StrategyEngine.BETTING_MARKET_VALUE

    def evaluate(
        self,
        context: BotTickContext,
        config: BettingMarketValueConfig,
    ) -> tuple[StrategyDecision, ...]:
        candidates = filter_candidates(
            tuple(candidate for candidate in context.candidates if candidate.betting.quotes),
            config.universe,
            f"{context.bot.id}:{context.as_of.date()}",
        )
        snapshots = {
            candidate.instrument_id: self._market_snapshots(candidate, context.as_of, config)
            for candidate in candidates
        }
        ranks = self._probability_ranks(snapshots)
        decisions: list[StrategyDecision] = []
        fallback_anchor = (
            median([float(c.current_price) for c in candidates]) if candidates else 0.0
        )

        for candidate in candidates:
            candidate_snapshots = snapshots[candidate.instrument_id]
            if len(candidate_snapshots) < config.betting_inputs.min_distinct_market_types:
                decisions.append(self._hold_without_coverage(candidate, candidate_snapshots))
                continue

            weighted_ranks: list[tuple[float, float]] = []
            weighted_movements: list[tuple[float, float]] = []
            component_scores: list[float] = []
            observation_depths: list[float] = []
            oldest_observed_at = min(
                snapshot.latest_observed_at for snapshot in candidate_snapshots.values()
            )
            latest_observed_at = max(
                snapshot.latest_observed_at for snapshot in candidate_snapshots.values()
            )
            for market_type, snapshot in candidate_snapshots.items():
                weight = config.betting_inputs.market_type_weights[market_type]
                probability_rank = ranks.get(market_type, {}).get(candidate.instrument_id, 0.0)
                weighted_ranks.append((probability_rank, weight))
                weighted_movements.append((snapshot.movement, weight))
                component_scores.append(probability_rank + snapshot.movement)
                observation_depths.append(snapshot.observation_depth)

            probability_rank = _weighted_average(weighted_ranks)
            probability_movement = _weighted_average(weighted_movements)
            # Goals, assists and score-or-assist share evidence; count that family once.
            families = {}
            for market_type, score in zip(candidate_snapshots, component_scores):
                family = (
                    "shots" if market_type in {"SHOTS", "SHOTS_ON_TARGET"} else "goal_involvement"
                )
                families.setdefault(family, []).append(score)
            confirmation = _confirmation_score(
                [fmean(scores) for scores in families.values()]
            ) * min(len(families) / 2, 1.0)
            anchor = (
                float(candidate.reference_price)
                if candidate.reference_price is not None
                else fallback_anchor
            )
            fair_price = anchor * max(
                0.1, 1.0 + 0.5 * probability_rank + 0.25 * probability_movement
            )
            valuation_gap = (
                fair_price / float(candidate.current_price) - 1.0
                if candidate.current_price > 0
                else 0.0
            )
            value_score = clamp(valuation_gap / 0.25, -1.0, 1.0)
            alpha = (
                config.signal_weights.get("implied_probability_rank", 0.0) * value_score
                + config.signal_weights.get("probability_movement", 0.0) * probability_movement
                + config.signal_weights.get("cross_market_confirmation", 0.0) * confirmation
            )
            freshness = _freshness_score(
                context.as_of,
                oldest_observed_at,
                config.lookbacks.max_quote_age_minutes,
            )
            configured_market_count = len(config.betting_inputs.market_type_weights)
            coverage = min(len(candidate_snapshots) / configured_market_count, 1.0)
            confidence = clamp(
                0.3
                + 0.25 * fmean(observation_depths)
                + 0.2 * freshness
                + 0.15 * coverage
                + 0.1 * abs(alpha),
                0.0,
                1.0,
            )
            side = DecisionSide.HOLD
            if (
                abs(alpha) > config.decision.hold_band
                and confidence >= config.decision.min_confidence
            ):
                if alpha >= config.decision.buy_threshold and valuation_gap >= 0.05:
                    side = DecisionSide.BUY
                elif (
                    config.decision.allow_sells
                    and candidate.current_holding_quantity > 0
                    and alpha <= config.decision.sell_threshold
                    and valuation_gap <= -0.05
                ):
                    side = DecisionSide.SELL

            suggested_cash_pct = config.sizing.base_cash_pct * (
                1.0
                + config.sizing.confidence_multiplier * confidence
                + config.sizing.movement_multiplier * abs(probability_movement)
            )
            decisions.append(
                StrategyDecision(
                    instrument_id=candidate.instrument_id,
                    side=side,
                    alpha_score=alpha,
                    expected_return=valuation_gap,
                    confidence=confidence,
                    suggested_cash_pct=suggested_cash_pct,
                    reason={
                        "engine": self.strategy_engine.value,
                        "implied_probability_rank": probability_rank,
                        "fair_price": fair_price,
                        "valuation_gap": valuation_gap,
                        "independent_market_families": len(families),
                        "probability_movement": probability_movement,
                        "cross_market_confirmation": confirmation,
                        "market_type_count": len(candidate_snapshots),
                        "latest_observed_at": latest_observed_at.isoformat(),
                        "oldest_observed_at": oldest_observed_at.isoformat(),
                    },
                )
            )

        return sorted_decisions(decisions)

    def _market_snapshots(
        self,
        candidate: CandidateInstrumentContext,
        as_of: datetime,
        config: BettingMarketValueConfig,
    ) -> dict[str, _MarketTypeSnapshot]:
        configured_types = config.betting_inputs.market_type_weights
        eligible_quotes = [
            quote
            for quote in candidate.betting.quotes
            if quote.market_type in configured_types
            and _as_utc(quote.observed_at) <= _as_utc(as_of)
            and (quote.kickoff_at is not None and _as_utc(quote.kickoff_at) > _as_utc(as_of))
            and _as_utc(quote.observed_at)
            >= _as_utc(as_of)
            - timedelta(
                minutes=config.lookbacks.max_quote_age_minutes + config.lookbacks.movement_minutes
            )
        ]
        event_quotes = _nearest_event_quotes(eligible_quotes, as_of)
        grouped: dict[str, list[BettingMarketQuote]] = {}
        for quote in event_quotes:
            grouped.setdefault(quote.canonical_selection_key, []).append(quote)

        movement_start = _as_utc(as_of) - timedelta(minutes=config.lookbacks.movement_minutes)
        fresh_after = _as_utc(as_of) - timedelta(minutes=config.lookbacks.max_quote_age_minutes)
        by_market_type: dict[str, list[tuple[float, float, float, datetime]]] = {}
        for quotes in grouped.values():
            ordered = sorted(quotes, key=lambda quote: _as_utc(quote.observed_at))
            latest = ordered[-1]
            if _as_utc(latest.observed_at) < fresh_after:
                continue
            # Only compare the probability of at least one event; never average different lines.
            if not _comparable_selection(latest):
                continue
            latest_probability = _normalized_probability(latest, event_quotes)
            if latest_probability < config.betting_inputs.min_implied_probability:
                continue
            history = [quote for quote in ordered if _as_utc(quote.observed_at) >= movement_start]
            # Repository contexts retain the first/last observation and carry the full
            # window count. Explicit contexts may instead contain every observation.
            observation_count = max(
                len({quote.observed_at for quote in history}),
                max((quote.observation_count for quote in history), default=0),
            )
            if observation_count < max(2, config.betting_inputs.min_observations_per_selection):
                continue
            if len({quote.observed_at for quote in history}) < 2:
                continue
            if (
                _as_utc(history[-1].observed_at) - _as_utc(history[0].observed_at)
            ).total_seconds() < 60:
                continue
            previous_probability = _normalized_probability(history[0], event_quotes)
            movement = 0.0
            if len(history) > 1 and previous_probability > 0:
                movement = clamp(
                    ((latest_probability - previous_probability) / previous_probability)
                    / config.betting_inputs.movement_scale,
                    -1.0,
                    1.0,
                )
            observation_depth = min(
                observation_count / max(4, config.betting_inputs.min_observations_per_selection),
                1.0,
            )
            by_market_type.setdefault(latest.market_type, []).append(
                (
                    latest_probability,
                    movement,
                    observation_depth,
                    latest.observed_at,
                )
            )

        return {
            market_type: _MarketTypeSnapshot(
                probability=fmean(item[0] for item in values),
                movement=fmean(item[1] for item in values),
                observation_depth=fmean(item[2] for item in values),
                latest_observed_at=min(item[3] for item in values),
            )
            for market_type, values in by_market_type.items()
        }

    def _probability_ranks(
        self,
        snapshots: Mapping[UUID, Mapping[str, _MarketTypeSnapshot]],
    ) -> dict[str, dict[UUID, float]]:
        values_by_type: dict[str, dict[UUID, float]] = {}
        for instrument_id, candidate_snapshots in snapshots.items():
            for market_type, snapshot in candidate_snapshots.items():
                values_by_type.setdefault(market_type, {})[instrument_id] = snapshot.probability
        return {
            market_type: _centered_ranks(values) for market_type, values in values_by_type.items()
        }

    def _hold_without_coverage(
        self,
        candidate: CandidateInstrumentContext,
        snapshots: Mapping[str, _MarketTypeSnapshot],
    ) -> StrategyDecision:
        return StrategyDecision(
            instrument_id=candidate.instrument_id,
            side=DecisionSide.HOLD,
            alpha_score=0.0,
            expected_return=0.0,
            confidence=0.0,
            suggested_cash_pct=0.0,
            reason={
                "engine": self.strategy_engine.value,
                "market_type_count": len(snapshots),
                "signal_present": bool(snapshots),
            },
        )


def _comparable_selection(quote: BettingMarketQuote) -> bool:
    from decimal import Decimal

    if quote.outcome_type == "ANYTIME":
        return quote.market_type in {"GOALSCORER", "ASSIST", "SCORE_OR_ASSIST"} and quote.line in {
            None,
            Decimal("1"),
        }
    return (quote.outcome_type == "AT_LEAST" and quote.line == Decimal("1")) or (
        quote.outcome_type == "OVER" and quote.line == Decimal("0.5")
    )


def _normalized_probability(quote: BettingMarketQuote, quotes: list[BettingMarketQuote]) -> float:
    probability = float(quote.implied_probability)
    if quote.outcome_type != "OVER":
        return probability
    opposite = [
        q
        for q in quotes
        if q.market_type == quote.market_type
        and q.line == quote.line
        and q.outcome_type == "UNDER"
        and q.observed_at == quote.observed_at
    ]
    if not opposite:
        return probability
    total = probability + float(opposite[-1].implied_probability)
    return probability / total if total > 0 else probability


def _nearest_event_quotes(
    quotes: list[BettingMarketQuote],
    as_of: datetime,
) -> list[BettingMarketQuote]:
    if not quotes:
        return []
    by_event: dict[str, list[BettingMarketQuote]] = {}
    for quote in quotes:
        by_event.setdefault(quote.provider_event_id, []).append(quote)

    def event_order(item: tuple[str, list[BettingMarketQuote]]) -> tuple[float, float]:
        event_quotes = item[1]
        kickoff_times = [quote.kickoff_at for quote in event_quotes if quote.kickoff_at is not None]
        if kickoff_times:
            distance = min(
                abs((_as_utc(kickoff_at) - _as_utc(as_of)).total_seconds())
                for kickoff_at in kickoff_times
            )
        else:
            distance = float("inf")
        newest = max(_as_utc(quote.observed_at).timestamp() for quote in event_quotes)
        return distance, -newest

    return min(by_event.items(), key=event_order)[1]


def _centered_ranks(values: Mapping[UUID, float]) -> dict[UUID, float]:
    return {key: value * 2.0 - 1.0 for key, value in rank_percentiles(values).items()}


def _weighted_average(values: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in values) / total_weight


def _confirmation_score(components: list[float]) -> float:
    combined = sum(components)
    if not components or combined == 0:
        return 0.0
    direction = 1.0 if combined > 0 else -1.0
    agreeing = sum(1 for component in components if component * direction > 0)
    agreement = agreeing / len(components)
    return direction * clamp((agreement - 0.5) * 2.0, 0.0, 1.0)


def _freshness_score(as_of: datetime, observed_at: datetime, max_age_minutes: int) -> float:
    age_minutes = max(
        (_as_utc(as_of) - _as_utc(observed_at)).total_seconds() / 60.0,
        0.0,
    )
    return clamp(1.0 - age_minutes / max_age_minutes, 0.0, 1.0)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
