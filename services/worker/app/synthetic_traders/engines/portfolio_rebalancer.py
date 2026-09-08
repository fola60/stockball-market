from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.synthetic_traders.config import PortfolioRebalancerConfig
from app.synthetic_traders.models import (
    BotTickContext,
    DecisionSide,
    StrategyDecision,
    StrategyEngine,
)

from .base import clamp, price_change_pct, sorted_decisions


@dataclass(frozen=True)
class PortfolioRebalancerStrategyEngine:
    strategy_engine: StrategyEngine = StrategyEngine.PORTFOLIO_REBALANCER

    def evaluate(
        self,
        context: BotTickContext,
        config: PortfolioRebalancerConfig,
    ) -> tuple[StrategyDecision, ...]:
        if context.portfolio.total_equity <= 0:
            return ()

        candidates_by_instrument = {
            candidate.instrument_id: candidate for candidate in context.candidates
        }
        decisions: list[StrategyDecision] = []
        cash_pct = float(context.portfolio.cash_balance / context.portfolio.total_equity)
        team_exposure = self._team_exposure(context)
        price_window_start = context.as_of - timedelta(days=7)

        for position in context.portfolio.positions:
            candidate = candidates_by_instrument.get(position.instrument_id)
            if candidate is None:
                continue
            position_pct = float(position.market_value / context.portfolio.total_equity)
            overweight = max(
                position_pct - config.portfolio_targets.max_player_position_pct,
                0.0,
            )
            team_overweight = 0.0
            if position.club is not None:
                team_overweight = max(
                    team_exposure.get(position.club, 0.0)
                    - config.portfolio_targets.max_team_exposure_pct,
                    0.0,
                )
            profit_take = 0.0
            if position.unrealized_return_pct is not None:
                if position.unrealized_return_pct >= config.rebalance_rules.profit_take_return_pct:
                    profit_take = position.unrealized_return_pct
            loss_reduce = 0.0
            if position.unrealized_return_pct is not None:
                if position.unrealized_return_pct <= config.rebalance_rules.loss_reduce_return_pct:
                    loss_reduce = abs(position.unrealized_return_pct)
            cash_raise = max(
                config.portfolio_targets.target_cash_pct - cash_pct,
                0.0,
            )
            concentration_risk = max(overweight, team_overweight)
            sell_need = max(concentration_risk, cash_raise, profit_take, loss_reduce)
            confidence = clamp(
                sell_need * 2.0 + (0.2 if position.quantity > 0 else 0.0),
                0.0,
                1.0,
            )
            alpha = -(
                config.signal_weights.get("portfolio_drift", 0.0) * overweight
                + config.signal_weights.get("cash_drift", 0.0) * cash_raise
                + config.signal_weights.get("concentration_risk", 0.0) * concentration_risk
                + config.signal_weights.get("profit_taking", 0.0) * max(profit_take, loss_reduce)
            )
            side = DecisionSide.HOLD
            if (
                config.decision.allow_sells
                and sell_need >= config.decision.rebalance_threshold
                and confidence >= config.decision.min_confidence
            ):
                side = DecisionSide.SELL
            suggested_cash_pct = config.sizing.base_rebalance_pct * max(
                sell_need,
                config.rebalance_rules.player_overweight_threshold_pct,
            )
            decisions.append(
                StrategyDecision(
                    instrument_id=position.instrument_id,
                    side=side,
                    alpha_score=alpha,
                    expected_return=-(sell_need),
                    confidence=confidence,
                    suggested_cash_pct=suggested_cash_pct,
                    reason={
                        "engine": self.strategy_engine.value,
                        "overweight_pct": overweight,
                        "team_overweight_pct": team_overweight,
                        "cash_raise_pct": cash_raise,
                        "profit_take": profit_take,
                        "loss_reduce": loss_reduce,
                    },
                )
            )

        cash_deploy_need = max(
            cash_pct - config.portfolio_targets.target_cash_pct,
            0.0,
        )
        buy_candidates = [
            candidate
            for candidate in context.candidates
            if not (
                config.candidate_selection.avoid_frozen_or_inactive_instruments
                and candidate.trading_status != "ACTIVE"
            )
        ]
        buy_candidates.sort(
            key=lambda candidate: self._buy_priority(
                candidate,
                price_window_start,
                context,
                config,
            ),
            reverse=True,
        )
        for candidate in buy_candidates[: config.candidate_selection.max_buy_candidates]:
            if not config.decision.allow_buys:
                break
            if (
                not config.rebalance_rules.allow_new_positions
                and candidate.current_holding_quantity <= 0
            ):
                continue
            if len(context.portfolio.positions) >= config.portfolio_targets.max_position_count:
                continue
            if candidate.current_holding_value > 0:
                position_pct = float(candidate.current_holding_value / context.portfolio.total_equity)
                if position_pct >= config.portfolio_targets.max_player_position_pct:
                    continue
            alpha_tiebreaker = self._alpha_tiebreaker(candidate, price_window_start)
            buy_need = max(
                cash_deploy_need,
                0.0,
            )
            confidence = clamp(
                buy_need * 2.0 + max(alpha_tiebreaker, 0.0) * 0.3,
                0.0,
                1.0,
            )
            alpha = (
                config.signal_weights.get("cash_drift", 0.0) * buy_need
                + config.signal_weights.get("portfolio_drift", 0.0) * max(0.0, 1.0 - cash_pct)
                + config.signal_weights.get("positive_alpha_tiebreaker", 0.0) * alpha_tiebreaker
            )
            side = DecisionSide.HOLD
            if (
                buy_need >= config.decision.rebalance_threshold
                and confidence >= config.decision.min_confidence
            ):
                side = DecisionSide.BUY
            suggested_cash_pct = (
                config.sizing.base_rebalance_pct
                * max(buy_need, config.rebalance_rules.cash_deploy_threshold_pct)
                * (
                    1.0
                    + config.sizing.cash_drift_multiplier * buy_need
                    + config.sizing.concentration_multiplier * max(alpha_tiebreaker, 0.0)
                )
            )
            decisions.append(
                StrategyDecision(
                    instrument_id=candidate.instrument_id,
                    side=side,
                    alpha_score=alpha,
                    expected_return=alpha_tiebreaker,
                    confidence=confidence,
                    suggested_cash_pct=suggested_cash_pct,
                    reason={
                        "engine": self.strategy_engine.value,
                        "cash_deploy_need": buy_need,
                        "alpha_tiebreaker": alpha_tiebreaker,
                        "position_count": len(context.portfolio.positions),
                    },
                )
            )

        return sorted_decisions(decisions)

    def _team_exposure(self, context: BotTickContext) -> dict[str, float]:
        exposure: dict[str, float] = {}
        if context.portfolio.total_equity <= 0:
            return exposure
        for position in context.portfolio.positions:
            if position.club is None:
                continue
            exposure[position.club] = exposure.get(position.club, 0.0) + float(
                position.market_value / context.portfolio.total_equity
            )
        return exposure

    def _buy_priority(
        self,
        candidate,
        price_window_start,
        context: BotTickContext,
        config: PortfolioRebalancerConfig,
    ) -> float:
        priority = self._alpha_tiebreaker(candidate, price_window_start)
        if candidate.current_holding_quantity > 0:
            priority += 0.15
        if config.candidate_selection.prefer_existing_watchlist and candidate.current_holding_quantity > 0:
            priority += 0.1
        if candidate.current_holding_value < config.portfolio_targets.min_position_cash_value:
            priority += 0.05
        if candidate.trading_status == "ACTIVE":
            priority += 0.05
        return priority

    def _alpha_tiebreaker(self, candidate, price_window_start) -> float:
        price_momentum = price_change_pct(
            candidate.recent_prices,
            candidate.current_price,
            price_window_start,
        )
        stats_alpha = 0.0
        if candidate.stats.average_rating is not None:
            stats_alpha = clamp((candidate.stats.average_rating - 6.5) / 2.0, -1.0, 1.0)
        return clamp(price_momentum / 0.15, -1.0, 1.0) * 0.6 + stats_alpha * 0.4
