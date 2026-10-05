from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from app.clients.trading_engine import OrderSide
from app.synthetic_traders.config import MarketMomentumConfig
from app.synthetic_traders.models import (
    BotTickContext,
    DecisionSide,
    StrategyDecision,
    StrategyEngine,
)

from .base import (
    breakout_strength,
    buy_sell_pressure,
    clamp,
    filter_candidates,
    price_change_pct,
    rank_percentiles,
    sorted_decisions,
    trade_volume_cash,
    unique_trader_count,
    volatility_pct,
    window_trades,
)
from .base import (
    stats_confirmation as shared_stats_confirmation,
)


@dataclass(frozen=True)
class MarketMomentumStrategyEngine:
    strategy_engine: StrategyEngine = StrategyEngine.MARKET_MOMENTUM

    def evaluate(
        self,
        context: BotTickContext,
        config: MarketMomentumConfig,
    ) -> tuple[StrategyDecision, ...]:
        volume_start = context.as_of - timedelta(minutes=config.lookbacks.volume_window_minutes)
        candidates = filter_candidates(
            tuple(
                replace(c, recent_trades=tuple(window_trades(c.recent_trades, volume_start)))
                for c in context.candidates
            ),
            config.universe,
            f"{context.bot.id}:{context.as_of.date()}",
        )
        if not candidates:
            return ()
        originals = {c.instrument_id: c for c in context.candidates}
        candidates = [originals[c.instrument_id] for c in candidates]

        volume_window_start = context.as_of - timedelta(
            minutes=config.lookbacks.volume_window_minutes
        )
        trade_volume_ranks = rank_percentiles(
            {
                candidate.instrument_id: float(
                    trade_volume_cash(window_trades(candidate.recent_trades, volume_window_start))
                )
                for candidate in candidates
            }
        )

        decisions: list[StrategyDecision] = []
        for candidate in candidates:
            momentum_window_start = context.as_of - timedelta(
                minutes=config.lookbacks.price_momentum_minutes
            )
            pressure_window_start = context.as_of - timedelta(
                minutes=config.lookbacks.buy_sell_pressure_minutes
            )
            volatility_window_start = context.as_of - timedelta(
                days=config.lookbacks.volatility_window_days
            )
            breakout_window_start = context.as_of - timedelta(
                days=config.lookbacks.breakout_window_days
            )

            price_momentum = price_change_pct(
                candidate.recent_prices,
                candidate.current_price,
                momentum_window_start,
            )
            pressure_trades = window_trades(candidate.recent_trades, pressure_window_start)
            pressure = buy_sell_pressure(pressure_trades)
            volume_confirmation = trade_volume_ranks.get(candidate.instrument_id, 0.0) * 2.0 - 1.0
            breakout = breakout_strength(
                candidate.recent_prices,
                candidate.current_price,
                breakout_window_start,
            )
            unique_participation = clamp(
                unique_trader_count([t for t in pressure_trades if t.side is OrderSide.BUY])
                / max(config.market_inputs.crowded_unique_buyer_threshold, 1),
                0.0,
                1.0,
            )
            volatility = volatility_pct(candidate.recent_prices, volatility_window_start)
            crowded_trade = 0.0
            if pressure > config.market_inputs.buy_pressure_threshold:
                crowded_trade = unique_participation
            stats_confirmation = shared_stats_confirmation(candidate.stats)
            volatility_risk = clamp(
                volatility / max(config.risk.volatility_tolerance, 0.01),
                0.0,
                1.0,
            )
            alpha = (
                config.signal_weights.get("price_momentum", 0.0)
                * clamp(
                    price_momentum / max(config.market_inputs.min_price_move_pct, 0.01), -1.0, 1.0
                )
                + config.signal_weights.get("buy_sell_pressure", 0.0) * pressure
                + config.signal_weights.get("volume_confirmation", 0.0) * volume_confirmation
                + config.signal_weights.get("breakout_strength", 0.0)
                * clamp(
                    breakout / max(config.market_inputs.breakout_near_high_pct, 0.01),
                    -1.0,
                    1.0,
                )
                + config.signal_weights.get("unique_trader_participation", 0.0)
                * unique_participation
                + config.signal_weights.get("stats_confirmation", 0.0) * stats_confirmation
                + config.signal_weights.get("crowded_trade", 0.0) * crowded_trade
                + config.signal_weights.get("volatility_risk", 0.0) * volatility_risk
            )
            confidence = clamp(
                abs(price_momentum) * 3.0
                + abs(pressure) * 0.5
                + max(volume_confirmation, 0.0) * 0.5
                - volatility_risk * 0.35,
                0.0,
                1.0,
            )
            side = DecisionSide.HOLD
            if (
                abs(alpha) > config.decision.hold_band
                and confidence >= config.decision.min_confidence
            ):
                if (
                    alpha >= config.decision.buy_threshold
                    and price_momentum >= config.market_inputs.min_price_move_pct
                    and pressure >= config.market_inputs.buy_pressure_threshold
                    and (config.market_inputs.allow_chasing_new_highs or breakout < 0)
                ):
                    side = DecisionSide.BUY
                elif (
                    config.decision.allow_sells
                    and candidate.current_holding_quantity > 0
                    and alpha <= config.decision.sell_threshold
                ):
                    if price_momentum < 0 or (
                        config.market_inputs.allow_fading_failed_breakouts
                        and breakout < -config.market_inputs.breakout_near_high_pct
                    ):
                        side = DecisionSide.SELL

            suggested_cash_pct = config.sizing.base_cash_pct * (
                1.0
                + config.sizing.confidence_multiplier * confidence
                + config.sizing.momentum_multiplier * max(price_momentum, 0.0)
                + config.sizing.volume_multiplier * max(volume_confirmation, 0.0)
            )
            decisions.append(
                StrategyDecision(
                    instrument_id=candidate.instrument_id,
                    side=side,
                    alpha_score=alpha,
                    expected_return=price_momentum,
                    confidence=confidence,
                    suggested_cash_pct=suggested_cash_pct,
                    reason={
                        "engine": self.strategy_engine.value,
                        "price_momentum": price_momentum,
                        "buy_sell_pressure": pressure,
                        "volume_confirmation": volume_confirmation,
                        "breakout_strength": breakout,
                        "unique_participation": unique_participation,
                        "volatility_risk": volatility_risk,
                    },
                )
            )

        return sorted_decisions(decisions)
