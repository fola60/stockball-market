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

from .base import clamp, price_change_pct, sorted_decisions, stats_confirmation, volatility_pct


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
            if candidate is None or candidate.trading_status != "ACTIVE":
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
            cash_trigger = (
                cash_pct < config.portfolio_targets.min_cash_pct
                or cash_raise >= config.rebalance_rules.cash_raise_threshold_pct
            )
            triggered = (
                cash_trigger
                or overweight >= config.rebalance_rules.player_overweight_threshold_pct
                or team_overweight >= config.rebalance_rules.team_overweight_threshold_pct
                or profit_take > 0
                or loss_reduce > 0
            )
            confidence = 1.0 if triggered else 0.0
            alpha = -(
                config.signal_weights.get("portfolio_drift", 0.0) * overweight
                + config.signal_weights.get("cash_drift", 0.0) * cash_raise
                + config.signal_weights.get("concentration_risk", 0.0) * concentration_risk
                + config.signal_weights.get("profit_taking", 0.0) * max(profit_take, loss_reduce)
            )
            alpha += config.signal_weights.get("volatility_risk", 0.0) * clamp(
                volatility_pct(candidate.recent_prices, price_window_start)
                / max(config.risk.volatility_tolerance, 0.01),
                0.0,
                1.0,
            )
            side = DecisionSide.HOLD
            if config.decision.allow_sells and triggered:
                side = DecisionSide.SELL
            suggested_cash_pct = min(
                position_pct,
                max(
                    config.rebalance_rules.trim_to_target_pct * concentration_risk,
                    cash_raise if cash_trigger else 0.0,
                    config.sizing.base_rebalance_pct
                    * position_pct
                    * (1.0 + config.sizing.profit_take_multiplier * max(profit_take, loss_reduce))
                    if profit_take or loss_reduce
                    else 0.0,
                ),
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
                        "volatility_risk": clamp(
                            volatility_pct(candidate.recent_prices, price_window_start)
                            / max(config.risk.volatility_tolerance, 0.01),
                            0.0,
                            1.0,
                        ),
                    },
                )
            )

        decisions = list(sorted_decisions(decisions))[
            : config.candidate_selection.max_sell_candidates
        ]
        selling = {d.instrument_id for d in decisions if d.side is DecisionSide.SELL}
        cash_deploy_need = max(
            cash_pct - config.portfolio_targets.target_cash_pct,
            0.0,
        )
        buy_candidates = [
            candidate
            for candidate in context.candidates
            if candidate.instrument_id not in selling
            and not (
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
            if (
                candidate.current_holding_quantity <= 0
                and len(context.portfolio.positions) >= config.portfolio_targets.max_position_count
            ):
                continue
            if candidate.current_holding_value > 0:
                position_pct = float(
                    candidate.current_holding_value / context.portfolio.total_equity
                )
                if position_pct >= config.portfolio_targets.max_player_position_pct:
                    continue
            alpha_tiebreaker = self._alpha_tiebreaker(candidate, price_window_start)
            buy_need = max(
                cash_deploy_need,
                0.0,
            )
            triggered = (
                cash_pct > config.portfolio_targets.max_cash_pct
                or buy_need >= config.rebalance_rules.cash_deploy_threshold_pct
            )
            confidence = 1.0 if triggered else 0.0
            alpha = (
                config.signal_weights.get("cash_drift", 0.0) * buy_need
                + config.signal_weights.get("portfolio_drift", 0.0) * max(0.0, 1.0 - cash_pct)
                + config.signal_weights.get("positive_alpha_tiebreaker", 0.0) * alpha_tiebreaker
            )
            alpha += config.signal_weights.get("volatility_risk", 0.0) * clamp(
                volatility_pct(candidate.recent_prices, price_window_start)
                / max(config.risk.volatility_tolerance, 0.01),
                0.0,
                1.0,
            )
            side = DecisionSide.HOLD
            if triggered:
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
                        "volatility_risk": clamp(
                            volatility_pct(candidate.recent_prices, price_window_start)
                            / max(config.risk.volatility_tolerance, 0.01),
                            0.0,
                            1.0,
                        ),
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
        priority = (
            self._alpha_tiebreaker(candidate, price_window_start)
            if config.candidate_selection.prefer_positive_alpha_when_deploying_cash
            else 0.0
        )
        if candidate.current_holding_quantity > 0:
            priority += 0.15
        if (
            config.candidate_selection.prefer_existing_watchlist
            and candidate.current_holding_quantity > 0
        ):
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
        stats_alpha = stats_confirmation(candidate.stats)
        return clamp(price_momentum / 0.15, -1.0, 1.0) * 0.6 + stats_alpha * 0.4
