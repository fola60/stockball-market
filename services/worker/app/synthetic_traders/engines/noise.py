from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from random import Random

from app.synthetic_traders.config import NoiseConfig
from app.synthetic_traders.models import (
    BotTickContext,
    DecisionSide,
    StrategyDecision,
    StrategyEngine,
)

from .base import (
    average,
    clamp,
    filter_candidates,
    price_change_pct,
    rank_percentiles,
    sorted_decisions,
    unique_trader_count,
)


@dataclass
class NoiseStrategyEngine:
    random_source: Random = field(default_factory=Random)
    strategy_engine: StrategyEngine = StrategyEngine.NOISE

    def evaluate(
        self,
        context: BotTickContext,
        config: NoiseConfig,
    ) -> tuple[StrategyDecision, ...]:
        candidates = filter_candidates(context.candidates, config.universe)
        if not candidates:
            return ()

        popularity_inputs = {
            candidate.instrument_id: float(len(candidate.recent_trades) + unique_trader_count(candidate.recent_trades))
            for candidate in candidates
        }
        price_inputs = {candidate.instrument_id: float(candidate.current_price) for candidate in candidates}
        popularity_ranks = rank_percentiles(popularity_inputs)
        price_ranks = rank_percentiles(price_inputs)
        recent_window_start = context.as_of - timedelta(days=7)

        decisions: list[StrategyDecision] = []
        for candidate in candidates:
            popularity_bias = popularity_ranks.get(candidate.instrument_id, 0.0) * 2.0 - 1.0
            recognizable_bias = price_ranks.get(candidate.instrument_id, 0.0) * 2.0 - 1.0
            recent_move = price_change_pct(
                candidate.recent_prices,
                candidate.current_price,
                recent_window_start,
            )
            recent_mover_bias = clamp(recent_move / 0.12, -1.0, 1.0)
            favorite_bias = 0.0
            if candidate.club and candidate.club in config.universe.favorite_clubs:
                favorite_bias += config.randomness.favorite_club_bias
            if candidate.player_id and candidate.player_id in config.universe.favorite_player_ids:
                favorite_bias += config.randomness.favorite_club_bias
            favorite_bias += config.randomness.recognizable_player_bias * max(recognizable_bias, 0.0)
            holding_bias = 1.0 if candidate.current_holding_quantity > 0 else 0.0
            cash_pct = (
                0.0
                if context.portfolio.total_equity <= 0
                else float(context.portfolio.cash_balance / context.portfolio.total_equity)
            )
            cash_pressure = clamp((cash_pct - 0.2) / 0.25, -1.0, 1.0)
            random_component = self.random_source.uniform(
                config.randomness.random_alpha_min,
                config.randomness.random_alpha_max,
            )
            alpha = (
                config.signal_weights.get("random_component", 0.0) * random_component
                + config.signal_weights.get("popularity_bias", 0.0) * popularity_bias
                + config.signal_weights.get("recent_mover_bias", 0.0) * recent_mover_bias
                + config.signal_weights.get("favorite_bias", 0.0) * favorite_bias
                + config.signal_weights.get("holding_bias", 0.0) * holding_bias
                + config.signal_weights.get("cash_pressure", 0.0) * cash_pressure
                + config.signal_weights.get("volatility_risk", 0.0) * abs(recent_mover_bias)
                + config.randomness.buy_bias
                - (config.randomness.sell_bias if candidate.current_holding_quantity > 0 else 0.0)
            )
            confidence = clamp(0.2 + abs(alpha) * 0.7 + average([abs(popularity_bias), abs(recent_mover_bias)]) * 0.1, 0.0, 1.0)
            side = DecisionSide.HOLD
            if abs(alpha) > config.decision.hold_band and confidence >= config.decision.min_confidence:
                if alpha >= config.decision.buy_threshold:
                    side = DecisionSide.BUY
                elif (
                    config.decision.allow_sells
                    and candidate.current_holding_quantity > 0
                    and alpha <= config.decision.sell_threshold
                ):
                    side = DecisionSide.SELL

            sizing_multiplier = self.random_source.uniform(
                config.sizing.random_size_multiplier_min,
                config.sizing.random_size_multiplier_max,
            )
            suggested_cash_pct = config.sizing.base_cash_pct * (
                1.0 + config.sizing.confidence_multiplier * confidence
            ) * sizing_multiplier
            decisions.append(
                StrategyDecision(
                    instrument_id=candidate.instrument_id,
                    side=side,
                    alpha_score=alpha,
                    expected_return=recent_move,
                    confidence=confidence,
                    suggested_cash_pct=suggested_cash_pct,
                    reason={
                        "engine": self.strategy_engine.value,
                        "random_component": random_component,
                        "popularity_bias": popularity_bias,
                        "recent_mover_bias": recent_mover_bias,
                        "favorite_bias": favorite_bias,
                        "holding_bias": holding_bias,
                        "cash_pressure": cash_pressure,
                    },
                )
            )

        return sorted_decisions(decisions)
