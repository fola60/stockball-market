from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import log10

from app.synthetic_traders.config import StatsValueConfig
from app.synthetic_traders.models import (
    BotTickContext,
    DecisionSide,
    StrategyDecision,
    StrategyEngine,
)

from .base import (
    canonical_position_codes,
    clamp,
    filter_candidates,
    price_change_pct,
    rank_percentiles,
    sorted_decisions,
    volatility_pct,
)


@dataclass(frozen=True)
class StatsValueStrategyEngine:
    strategy_engine: StrategyEngine = StrategyEngine.STATS_VALUE

    def evaluate(
        self,
        context: BotTickContext,
        config: StatsValueConfig,
    ) -> tuple[StrategyDecision, ...]:
        candidates = filter_candidates(context.candidates, config.universe)
        if not candidates:
            return ()

        performance_raw = {
            candidate.instrument_id: self._performance_score(candidate, config)
            for candidate in candidates
        }
        market_value_raw = {
            candidate.instrument_id: (
                0.0
                if candidate.market_value_observation is None
                else log10(max(float(candidate.market_value_observation), 1.0))
            )
            for candidate in candidates
            if candidate.market_value_observation is not None
        }
        price_raw = {
            candidate.instrument_id: float(candidate.current_price) for candidate in candidates
        }
        performance_rank = rank_percentiles(performance_raw)
        market_value_rank = rank_percentiles(market_value_raw)
        price_rank = rank_percentiles(price_raw)
        momentum_window_start = context.as_of - timedelta(days=config.lookbacks.price_momentum_days)
        volatility_window_start = context.as_of - timedelta(days=max(config.lookbacks.price_momentum_days, 7))

        decisions: list[StrategyDecision] = []
        for candidate in candidates:
            stats_form = performance_rank.get(candidate.instrument_id, 0.5) * 2.0 - 1.0
            minutes_security = clamp(
                ((candidate.stats.average_minutes or 0.0) / 90.0) * 2.0 - 1.0,
                -1.0,
                1.0,
            )
            market_rank = market_value_rank.get(candidate.instrument_id, performance_rank.get(candidate.instrument_id, 0.5))
            valuation_gap = clamp(
                (
                    config.valuation.fair_value_blend.performance_implied_value
                    * performance_rank.get(candidate.instrument_id, 0.5)
                    + config.valuation.fair_value_blend.market_value_observation * market_rank
                    + config.valuation.fair_value_blend.current_stockball_price
                    * price_rank.get(candidate.instrument_id, 0.5)
                )
                - price_rank.get(candidate.instrument_id, 0.5),
                -config.valuation.cap_extreme_gap_at,
                config.valuation.cap_extreme_gap_at,
            )
            if config.valuation.cap_extreme_gap_at > 0:
                market_value_gap = valuation_gap / config.valuation.cap_extreme_gap_at
            else:
                market_value_gap = 0.0
            position_adjustment = 0.0
            if config.stats_inputs.position_baseline_enabled:
                position_codes = canonical_position_codes(candidate.position)
                if "FWD" in position_codes:
                    position_adjustment = 0.1
                elif "MID" in position_codes:
                    position_adjustment = 0.05
                elif "GK" in position_codes:
                    position_adjustment = -0.05
            price_momentum = price_change_pct(
                candidate.recent_prices,
                candidate.current_price,
                momentum_window_start,
            )
            volatility_risk = clamp(
                volatility_pct(candidate.recent_prices, volatility_window_start)
                / max(config.risk.volatility_tolerance, 0.01),
                0.0,
                1.0,
            )
            availability_risk = 0.0
            if candidate.stats.observation_count == 0:
                availability_risk = 1.0
            elif candidate.stats.average_minutes is not None and candidate.stats.average_minutes < 45:
                availability_risk = 0.6
            social_confirmation = clamp(candidate.social.sentiment_score, -1.0, 1.0)
            alpha = (
                config.signal_weights.get("stats_form", 0.0) * stats_form
                + config.signal_weights.get("minutes_security", 0.0) * minutes_security
                + config.signal_weights.get("market_value_gap", 0.0) * market_value_gap
                + config.signal_weights.get("fixture_context", 0.0) * 0.0
                + config.signal_weights.get("position_adjustment", 0.0) * position_adjustment
                + config.signal_weights.get("stockball_price_momentum", 0.0)
                * clamp(price_momentum / 0.15, -1.0, 1.0)
                + config.signal_weights.get("social_confirmation", 0.0) * social_confirmation
                + config.signal_weights.get("availability_risk", 0.0) * availability_risk
                + config.signal_weights.get("volatility_risk", 0.0) * volatility_risk
            )
            confidence = clamp(
                min(candidate.stats.observation_count / max(config.lookbacks.form_matches, 1), 1.0)
                * 0.5
                + (0.25 if candidate.market_value_observation is not None else 0.0)
                + min(abs(valuation_gap) * 1.5, 0.25),
                0.0,
                1.0,
            )
            side = DecisionSide.HOLD
            if abs(alpha) > config.decision.hold_band and confidence >= config.decision.min_confidence:
                if alpha >= config.decision.buy_threshold and valuation_gap >= config.valuation.min_valuation_gap_to_buy:
                    side = DecisionSide.BUY
                elif (
                    config.decision.allow_sells
                    and candidate.current_holding_quantity > 0
                    and alpha <= config.decision.sell_threshold
                    and valuation_gap <= -config.valuation.min_overvaluation_gap_to_sell
                ):
                    side = DecisionSide.SELL

            suggested_cash_pct = config.sizing.base_cash_pct * (
                1.0
                + config.sizing.confidence_multiplier * confidence
                + config.sizing.expected_return_multiplier * max(abs(valuation_gap), 0.0)
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
                        "stats_form": stats_form,
                        "minutes_security": minutes_security,
                        "market_value_gap": market_value_gap,
                        "availability_risk": availability_risk,
                        "volatility_risk": volatility_risk,
                    },
                )
            )

        return sorted_decisions(decisions)

    def _performance_score(self, candidate, config: StatsValueConfig) -> float:
        if candidate.stats.observation_count == 0:
            return 0.0
        rating_score = 0.0
        if candidate.stats.average_rating is not None:
            rating_score = clamp((candidate.stats.average_rating - 6.0) / 2.5, 0.0, 1.0)
        minutes_score = clamp((candidate.stats.average_minutes or 0.0) / 90.0, 0.0, 1.0)
        goals_score = clamp(candidate.stats.goals_per_match / 1.5, 0.0, 1.0)
        assists_score = clamp(candidate.stats.assists_per_match / 1.0, 0.0, 1.0)
        clean_sheet_score = clamp(candidate.stats.clean_sheets_per_match, 0.0, 1.0)
        defensive_score = clamp(candidate.stats.defensive_actions_per_match / 8.0, 0.0, 1.0)
        shots_score = clamp(candidate.stats.shots_per_match / 4.0, 0.0, 1.0)
        key_pass_score = clamp(candidate.stats.key_passes_per_match / 3.0, 0.0, 1.0)
        cards_penalty = clamp(candidate.stats.cards_per_match / 2.0, 0.0, 1.0)
        return (
            config.stats_inputs.rating_weight * rating_score
            + config.stats_inputs.goals_weight * goals_score
            + config.stats_inputs.assists_weight * assists_score
            + config.stats_inputs.clean_sheet_weight * clean_sheet_score
            + config.stats_inputs.defensive_actions_weight * defensive_score
            + config.stats_inputs.shots_weight * shots_score
            + config.stats_inputs.key_passes_weight * key_pass_score
            + config.stats_inputs.cards_penalty_weight * cards_penalty
            + 0.15 * minutes_score
        )
