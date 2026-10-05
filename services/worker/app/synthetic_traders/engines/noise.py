from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from random import Random
from typing import Sequence
from uuid import UUID

from app.synthetic_traders.config import NoiseConfig
from app.synthetic_traders.models import (
    BotTickContext,
    CandidateInstrumentContext,
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
        candidates = filter_candidates(
            context.candidates, config.universe, f"{context.bot.id}:{context.as_of.date()}"
        )
        if not candidates:
            return ()

        popularity_inputs = {
            candidate.instrument_id: float(
                len(candidate.recent_trades) + unique_trader_count(candidate.recent_trades)
            )
            for candidate in candidates
        }
        price_inputs = {
            candidate.instrument_id: float(candidate.current_price) for candidate in candidates
        }
        popularity_ranks = rank_percentiles(popularity_inputs)
        price_ranks = rank_percentiles(price_inputs)
        recent_window_start = context.as_of - timedelta(days=7)
        activity_floor = hourly_activity_floor_scores(
            candidates,
            context.as_of,
            config.randomness.activity_floor_minutes,
        )

        decisions: list[StrategyDecision] = []
        for candidate in candidates:
            popularity_bias = popularity_ranks.get(candidate.instrument_id, 0.0) * 2.0 - 1.0
            recognizable_bias = price_ranks.get(candidate.instrument_id, 0.0) * 2.0 - 1.0
            recent_move = price_change_pct(
                candidate.recent_prices,
                candidate.current_price,
                recent_window_start,
            )
            recent_mover_bias = clamp(recent_move / 0.12, -1.0, 1.0) * (
                1.0 + config.randomness.recent_mover_bias
            )
            favorite_bias = 0.0
            if not config.universe.favorite_clubs and not config.universe.favorite_player_ids:
                affinity = (
                    int.from_bytes(
                        sha256(f"{context.bot.id}:{candidate.player_id}".encode()).digest()[:4],
                        "big",
                    )
                    / 2**32
                )
                if affinity < 0.05:
                    favorite_bias = config.randomness.favorite_club_bias
            if candidate.club and candidate.club.casefold() in {
                club.casefold() for club in config.universe.favorite_clubs
            }:
                favorite_bias += config.randomness.favorite_club_bias
            if candidate.player_id and candidate.player_id in config.universe.favorite_player_ids:
                favorite_bias += config.randomness.favorite_club_bias
            favorite_bias += config.randomness.recognizable_player_bias * max(
                recognizable_bias, 0.0
            )
            holding_pct = (
                float(candidate.current_holding_value / context.portfolio.total_equity)
                if context.portfolio.total_equity > 0
                else 0.0
            )
            holding_bias = -clamp(
                holding_pct / max(config.risk.max_player_position_pct or 1.0, 0.01), 0.0, 1.0
            )
            # Personality controls reinforce inventory pressure rather than reward existing holdings.
            holding_bias *= 1.0 + config.randomness.holding_bias
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
            confidence = clamp(
                0.2
                + abs(alpha) * 0.7
                + average([abs(popularity_bias), abs(recent_mover_bias)]) * 0.1,
                0.0,
                1.0,
            )
            side = DecisionSide.HOLD
            if (
                abs(alpha) > config.decision.hold_band
                and confidence >= config.decision.min_confidence
            ):
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
            suggested_cash_pct = (
                config.sizing.base_cash_pct
                * (1.0 + config.sizing.confidence_multiplier * confidence)
                * sizing_multiplier
            )
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
                        "activity_floor": activity_floor[candidate.instrument_id],
                        "activity_bonus": config.randomness.activity_floor_weight
                        * activity_floor[candidate.instrument_id],
                    },
                )
            )

        return sorted_decisions(decisions)


def hourly_activity_floor_scores(
    candidates: Sequence[CandidateInstrumentContext],
    as_of: datetime,
    window_minutes: int,
) -> dict[UUID, float]:
    window_start = as_of - timedelta(minutes=window_minutes)
    counts = {
        candidate.instrument_id: sum(
            1 for trade in candidate.recent_trades if trade.executed_at >= window_start
        )
        for candidate in candidates
    }
    maximum = max(counts.values(), default=0)
    if maximum == 0:
        return {instrument_id: 1.0 for instrument_id in counts}
    return {instrument_id: 1.0 - count / maximum for instrument_id, count in counts.items()}
