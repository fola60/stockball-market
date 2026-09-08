from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from random import Random
from typing import Callable, Mapping
from uuid import UUID

from app.clients.trading_engine import (
    ExecuteOrderCommand,
    OrderSide,
    TradingEngineClient,
    TradingEngineClientError,
    TradingEngineUnavailableError,
)

from .config import (
    BettingMarketValueConfig,
    ExecutionConfig,
    PortfolioRebalancerConfig,
    StrategyConfig,
    SyntheticTraderConfigError,
    apply_config_overrides,
    parse_strategy_config,
)
from .engines import default_engine_registry
from .engines.base import candidate_exclusion_counts
from .models import (
    BotPortfolioContext,
    BotTickContext,
    CandidateInstrumentContext,
    DecisionSide,
    OrderIntent,
    StrategyDecision,
    StrategyEngine,
    SyntheticTraderTickBatchResult,
    SyntheticTraderTickDiagnostics,
    SyntheticTraderTickOutcome,
    TickOutcomeStatus,
)
from .repository import SyntheticTraderRepository

DECIMAL_QUANTITY_STEP = Decimal("0.000001")
DECIMAL_CASH_STEP = Decimal("0.0001")
DEFAULT_TICK_CADENCE_MINUTES = 60


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _config_overrides_cache_key(overrides: Mapping[str, object]) -> str:
    return json.dumps(overrides, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class SyntheticTraderService:
    repository: SyntheticTraderRepository
    trading_engine_client: TradingEngineClient
    random_source: Random = field(default_factory=Random)
    clock: Callable[[], datetime] = _utc_now
    engine_registry: Mapping[StrategyEngine, object] | None = None

    def __post_init__(self) -> None:
        if self.engine_registry is None:
            self.engine_registry = default_engine_registry(self.random_source)

    def tick_due_bots(
        self,
        as_of: datetime,
        *,
        limit: int = 100,
        force_timing: bool = False,
        bot_ids: tuple[UUID, ...] = (),
    ) -> SyntheticTraderTickBatchResult:
        outcomes: list[SyntheticTraderTickOutcome] = []
        diagnostics: list[SyntheticTraderTickDiagnostics] = []
        config_cache: dict[tuple[UUID, str], tuple[StrategyEngine, StrategyConfig]] = {}
        market_candidates_cache: dict[int | None, tuple[CandidateInstrumentContext, ...]] = {}
        bots = self.repository.list_due_bots(
            as_of,
            limit=limit,
            force_timing=force_timing,
            bot_ids=bot_ids,
        )

        for bot in bots:
            execution_config = ExecutionConfig(
                tick_cadence_minutes=DEFAULT_TICK_CADENCE_MINUTES,
                cooldown_minutes=0,
                decision_jitter_minutes=0,
                trade_probability=0.0,
                size_noise_pct=0.0,
                max_orders_per_tick=1,
            )
            try:
                cache_key = (bot.config_id, _config_overrides_cache_key(bot.config_overrides))
                cached = config_cache.get(cache_key)
                if cached is None:
                    config_record = self.repository.get_bot_config(bot.config_id)
                    if config_record is None:
                        raise LookupError(f"synthetic trader config {bot.config_id} was not found")
                    raw_config = apply_config_overrides(
                        config_record.config,
                        bot.config_overrides,
                    )
                    parsed_config = parse_strategy_config(
                        config_record.strategy_engine,
                        raw_config,
                    )
                    cached = (config_record.strategy_engine, parsed_config)
                    config_cache[cache_key] = cached
                strategy_engine, strategy_config = cached
                execution_config = strategy_config.execution

                portfolio = self.repository.load_portfolio_context(bot)
                activity = self.repository.load_activity_context(bot, as_of)
                betting_lookback_minutes = (
                    strategy_config.lookbacks.movement_minutes
                    if isinstance(strategy_config, BettingMarketValueConfig)
                    else None
                )
                market_candidates = market_candidates_cache.get(betting_lookback_minutes)
                if market_candidates is None:
                    loaded_candidates = self.repository.load_candidate_instruments(
                        portfolio,
                        as_of,
                        betting_lookback_minutes=betting_lookback_minutes,
                    )
                    market_candidates = _without_portfolio_holdings(loaded_candidates)
                    market_candidates_cache[betting_lookback_minutes] = market_candidates
                candidates = _with_portfolio_holdings(market_candidates, portfolio)
                context = BotTickContext(
                    bot=bot,
                    portfolio=portfolio,
                    activity=activity,
                    candidates=candidates,
                    as_of=as_of,
                )
                engine = self.engine_registry.get(strategy_engine) if self.engine_registry else None
                if engine is None:
                    raise LookupError(f"no strategy engine registered for {strategy_engine.value}")

                decisions = engine.evaluate(context, strategy_config)
                rejection_reasons: Counter[str] = Counter()
                recovery_decisions = self._build_recovery_decisions(
                    context=context,
                    strategy_config=strategy_config,
                    decisions=decisions,
                )
                recovery_instruments = {
                    decision.instrument_id for decision in recovery_decisions
                }
                planned_decisions = recovery_decisions + tuple(
                    decision
                    for decision in decisions
                    if decision.instrument_id not in recovery_instruments
                )
                intents = self._build_order_intents(
                    context=context,
                    strategy_config=strategy_config,
                    decisions=planned_decisions,
                    bypass_cooldown=force_timing,
                    bypass_daily_trade_limit=force_timing,
                    rejection_reasons=rejection_reasons,
                )
                diagnostic_candidates = context.candidates
                if isinstance(strategy_config, BettingMarketValueConfig):
                    missing_quotes = sum(
                        1 for candidate in context.candidates if not candidate.betting.quotes
                    )
                    diagnostic_candidates = tuple(
                        candidate for candidate in context.candidates if candidate.betting.quotes
                    )
                else:
                    missing_quotes = 0
                exclusions = (
                    candidate_exclusion_counts(diagnostic_candidates, strategy_config.universe)
                    if hasattr(strategy_config, "universe")
                    else {}
                )
                if missing_quotes:
                    exclusions["missing_betting_quotes"] = missing_quotes
                diagnostics.append(
                    SyntheticTraderTickDiagnostics(
                        bot_id=bot.id,
                        strategy_engine=strategy_engine,
                        candidates_loaded=len(context.candidates),
                        candidates_evaluated=len(decisions),
                        candidate_exclusions=exclusions,
                        decisions=dict(Counter(decision.side.value for decision in decisions)),
                        negative_alpha=self._negative_alpha_counts(decisions, strategy_config),
                        rejection_reasons=dict(rejection_reasons),
                        recovery_decisions=len(recovery_decisions),
                        recovery_orders=sum(
                            1
                            for intent in intents
                            if intent.reason.get("engine") == "PORTFOLIO_RECOVERY"
                        ),
                    )
                )
                if not intents:
                    outcomes.append(
                        SyntheticTraderTickOutcome(
                            bot_id=bot.id,
                            account_id=bot.account_id,
                            portfolio_id=bot.portfolio_id,
                            status=TickOutcomeStatus.SKIPPED,
                            message="no order passed strategy and risk checks",
                        )
                    )
                else:
                    outcomes.extend(self._submit_intents(context, intents))
            except (LookupError, SyntheticTraderConfigError) as exc:
                outcomes.append(
                    SyntheticTraderTickOutcome(
                        bot_id=bot.id,
                        account_id=bot.account_id,
                        portfolio_id=bot.portfolio_id,
                        status=TickOutcomeStatus.FAILED,
                        message=str(exc),
                    )
                )
            finally:
                self.repository.update_tick_state(
                    bot.id,
                    last_ticked_at=as_of,
                    next_tick_after=self._next_tick_after(as_of, execution_config),
                )

        return SyntheticTraderTickBatchResult(
            processed_bots=len(bots),
            outcomes=tuple(outcomes),
            diagnostics=tuple(diagnostics),
        )

    def _submit_intents(
        self,
        context: BotTickContext,
        intents: list[OrderIntent],
    ) -> list[SyntheticTraderTickOutcome]:
        outcomes: list[SyntheticTraderTickOutcome] = []
        for intent in intents:
            try:
                execution = self.trading_engine_client.execute_order(
                    ExecuteOrderCommand(
                        request_id=intent.request_id,
                        account_id=context.bot.account_id,
                        portfolio_id=context.bot.portfolio_id,
                        instrument_id=intent.instrument_id,
                        side=intent.side,
                        quantity=_format_decimal(intent.quantity, places=6),
                    )
                )
            except TradingEngineUnavailableError as exc:
                outcomes.append(
                    SyntheticTraderTickOutcome(
                        bot_id=context.bot.id,
                        account_id=context.bot.account_id,
                        portfolio_id=context.bot.portfolio_id,
                        status=TickOutcomeStatus.FAILED,
                        request_id=intent.request_id,
                        instrument_id=intent.instrument_id,
                        side=intent.side,
                        message=str(exc),
                    )
                )
                continue
            except TradingEngineClientError as exc:
                outcomes.append(
                    SyntheticTraderTickOutcome(
                        bot_id=context.bot.id,
                        account_id=context.bot.account_id,
                        portfolio_id=context.bot.portfolio_id,
                        status=TickOutcomeStatus.FAILED,
                        request_id=intent.request_id,
                        instrument_id=intent.instrument_id,
                        side=intent.side,
                        message=str(exc.body.get("message", "trading engine request failed")),
                        error_code=str(exc.body.get("code", "trading_engine_error")),
                        error_details=(
                            exc.body.get("details")
                            if isinstance(exc.body.get("details"), dict)
                            else None
                        ),
                    )
                )
                continue

            outcomes.append(
                SyntheticTraderTickOutcome(
                    bot_id=context.bot.id,
                    account_id=context.bot.account_id,
                    portfolio_id=context.bot.portfolio_id,
                    status=TickOutcomeStatus.SUBMITTED,
                    request_id=intent.request_id,
                    instrument_id=intent.instrument_id,
                    side=intent.side,
                    execution=execution,
                )
            )
        return outcomes

    def _build_order_intents(
        self,
        *,
        context: BotTickContext,
        strategy_config: StrategyConfig,
        decisions: tuple[StrategyDecision, ...],
        bypass_cooldown: bool = False,
        bypass_daily_trade_limit: bool = False,
        rejection_reasons: Counter[str] | None = None,
    ) -> list[OrderIntent]:
        rejections = rejection_reasons if rejection_reasons is not None else Counter()
        if context.portfolio.total_equity <= 0:
            rejections["non_positive_equity"] += 1
            return []
        if (
            not bypass_cooldown
            and context.activity.last_order_at is not None
            and strategy_config.execution.cooldown_minutes > 0
            and context.as_of - context.activity.last_order_at
            < timedelta(minutes=strategy_config.execution.cooldown_minutes)
        ):
            rejections["cooldown"] += 1
            return []

        available_cash = context.portfolio.cash_balance
        total_equity = context.portfolio.total_equity
        daily_turnover_cash = context.activity.daily_turnover_cash
        existing_trade_count = context.activity.daily_trade_count
        accepted_orders = 0
        positions_by_instrument = {
            position.instrument_id: position for position in context.portfolio.positions
        }
        team_exposure = self._team_exposure(context.portfolio)
        candidates_by_instrument = {
            candidate.instrument_id: candidate for candidate in context.candidates
        }

        intents: list[OrderIntent] = []
        for decision in decisions:
            if decision.side is DecisionSide.HOLD:
                continue
            if accepted_orders >= strategy_config.execution.max_orders_per_tick:
                rejections["max_orders_per_tick"] += 1
                break
            if (
                not bypass_daily_trade_limit
                and existing_trade_count + accepted_orders
                >= strategy_config.risk.max_daily_trades
            ):
                rejections["max_daily_trades"] += 1
                break
            is_recovery = decision.reason.get("engine") == "PORTFOLIO_RECOVERY"
            if (
                not is_recovery
                and self.random_source.random() > strategy_config.execution.trade_probability
            ):
                rejections["trade_probability"] += 1
                continue

            candidate = candidates_by_instrument.get(decision.instrument_id)
            if candidate is None:
                rejections["candidate_unavailable"] += 1
                continue
            if candidate.current_price <= 0:
                rejections["invalid_price"] += 1
                continue

            requested_notional = _quantize_cash(
                total_equity * Decimal(str(max(decision.suggested_cash_pct, 0.0)))
            )
            if requested_notional <= 0:
                rejections["non_positive_requested_notional"] += 1
                continue
            if not is_recovery:
                requested_notional = self._apply_size_adjustments(
                    strategy_config,
                    decision=decision,
                    candidate=candidate,
                    requested_notional=requested_notional,
                )
            if requested_notional <= 0:
                rejections["size_adjustment"] += 1
                continue

            if decision.side is DecisionSide.BUY:
                intent = self._plan_buy_intent(
                    context=context,
                    strategy_config=strategy_config,
                    decision=decision,
                    candidate=candidate,
                    available_cash=available_cash,
                    team_exposure=team_exposure,
                    requested_notional=requested_notional,
                    rejection_reasons=rejections,
                )
            else:
                intent = self._plan_sell_intent(
                    context=context,
                    strategy_config=strategy_config,
                    decision=decision,
                    candidate=candidate,
                    requested_notional=requested_notional,
                    position=positions_by_instrument.get(candidate.instrument_id),
                    rejection_reasons=rejections,
                )
            if intent is None:
                continue

            next_turnover = daily_turnover_cash + intent.notional_cash
            if (
                total_equity > 0
                and float(next_turnover / total_equity)
                > strategy_config.risk.max_daily_turnover_pct
            ):
                rejections["max_daily_turnover"] += 1
                continue

            intents.append(intent)
            accepted_orders += 1
            daily_turnover_cash = next_turnover
            if intent.side is OrderSide.BUY:
                available_cash -= intent.notional_cash
                team_exposure = self._apply_team_exposure(
                    team_exposure,
                    candidate,
                    intent.notional_cash,
                )
            else:
                available_cash += intent.notional_cash
                team_exposure = self._apply_team_exposure(
                    team_exposure,
                    candidate,
                    -intent.notional_cash,
                )

        return intents

    def _build_recovery_decisions(
        self,
        *,
        context: BotTickContext,
        strategy_config: StrategyConfig,
        decisions: tuple[StrategyDecision, ...],
    ) -> tuple[StrategyDecision, ...]:
        total_equity = context.portfolio.total_equity
        if total_equity <= 0 or not context.portfolio.positions:
            return ()

        min_cash_pct = self._min_cash_reserve_pct(strategy_config)
        cash_deficit = Decimal("0")
        if min_cash_pct is not None:
            cash_deficit = max(
                _quantize_cash(total_equity * Decimal(str(min_cash_pct)))
                - context.portfolio.cash_balance,
                Decimal("0"),
            )

        max_player_pct = self._max_player_position_pct(strategy_config)
        max_team_pct = self._max_team_exposure_pct(strategy_config)
        team_exposure = self._team_exposure(context.portfolio)
        candidates = {candidate.instrument_id: candidate for candidate in context.candidates}
        strategy_decisions = {decision.instrument_id: decision for decision in decisions}
        recovery: list[tuple[float, float, Decimal, StrategyDecision]] = []

        for position in context.portfolio.positions:
            candidate = candidates.get(position.instrument_id)
            if candidate is None or candidate.current_price <= 0 or candidate.trading_status != "ACTIVE":
                continue
            triggers: list[str] = []
            requested_notional = cash_deficit
            if cash_deficit > 0:
                triggers.append("cash_below_reserve")
            if max_player_pct is not None:
                player_excess = position.market_value - _quantize_cash(
                    total_equity * Decimal(str(max_player_pct))
                )
                if player_excess > 0:
                    triggers.append("player_overexposure")
                    requested_notional = max(requested_notional, player_excess)
            if max_team_pct is not None and position.club is not None:
                team_excess = team_exposure.get(position.club, Decimal("0")) - _quantize_cash(
                    total_equity * Decimal(str(max_team_pct))
                )
                if team_excess > 0:
                    triggers.append("team_overexposure")
                    requested_notional = max(requested_notional, team_excess)
            if not triggers or requested_notional <= 0:
                continue

            strategy_decision = strategy_decisions.get(position.instrument_id)
            alpha = strategy_decision.alpha_score if strategy_decision is not None else 0.0
            unrealized_return = position.unrealized_return_pct or 0.0
            recovery.append(
                (
                    alpha,
                    unrealized_return,
                    -position.market_value,
                    StrategyDecision(
                        instrument_id=position.instrument_id,
                        side=DecisionSide.SELL,
                        alpha_score=alpha,
                        expected_return=unrealized_return,
                        confidence=1.0,
                        suggested_cash_pct=float(min(requested_notional / total_equity, Decimal("1"))),
                        reason={
                            "engine": "PORTFOLIO_RECOVERY",
                            "triggers": triggers,
                            "strategy_alpha": alpha,
                            "cash_deficit": str(cash_deficit),
                        },
                    ),
                )
            )

        recovery.sort(key=lambda item: item[:3])
        return tuple(item[3] for item in recovery)

    def _negative_alpha_counts(
        self,
        decisions: tuple[StrategyDecision, ...],
        strategy_config: StrategyConfig,
    ) -> dict[str, int]:
        sell_threshold = getattr(strategy_config.decision, "sell_threshold", None)
        if sell_threshold is None:
            return {"below_zero": sum(1 for decision in decisions if decision.alpha_score < 0)}
        return {
            "at_or_below_sell_threshold": sum(
                1 for decision in decisions if decision.alpha_score <= sell_threshold
            ),
            "below_zero_above_sell_threshold": sum(
                1
                for decision in decisions
                if sell_threshold < decision.alpha_score < 0
            ),
        }

    def _plan_buy_intent(
        self,
        *,
        context: BotTickContext,
        strategy_config: StrategyConfig,
        decision: StrategyDecision,
        candidate: CandidateInstrumentContext,
        available_cash: Decimal,
        team_exposure: dict[str, Decimal],
        requested_notional: Decimal,
        rejection_reasons: Counter[str],
    ) -> OrderIntent | None:
        min_cash_reserve_pct = self._min_cash_reserve_pct(strategy_config)
        max_player_position_pct = self._max_player_position_pct(strategy_config)
        max_team_exposure_pct = self._max_team_exposure_pct(strategy_config)
        total_equity = context.portfolio.total_equity
        reserve_cash = (
            Decimal("0")
            if min_cash_reserve_pct is None
            else _quantize_cash(total_equity * Decimal(str(min_cash_reserve_pct)))
        )
        max_trade_notional = _quantize_cash(
            total_equity * Decimal(str(strategy_config.risk.max_trade_cash_pct))
        )
        notional = min(
            requested_notional,
            available_cash - reserve_cash,
            strategy_config.risk.max_trade_cash_amount,
            max_trade_notional,
        )
        if available_cash - reserve_cash <= 0:
            rejection_reasons["cash_reserve"] += 1
        if max_player_position_pct is not None:
            current_value = candidate.current_holding_value
            remaining_capacity = _quantize_cash(
                total_equity * Decimal(str(max_player_position_pct)) - current_value
            )
            notional = min(notional, remaining_capacity)
            if remaining_capacity <= 0:
                rejection_reasons["player_exposure"] += 1
        if max_team_exposure_pct is not None and candidate.club is not None:
            current_team_exposure = team_exposure.get(candidate.club, Decimal("0"))
            remaining_team_capacity = _quantize_cash(
                total_equity * Decimal(str(max_team_exposure_pct)) - current_team_exposure
            )
            notional = min(notional, remaining_team_capacity)
            if remaining_team_capacity <= 0:
                rejection_reasons["team_exposure"] += 1

        notional = _quantize_cash(notional)
        if notional < strategy_config.risk.min_trade_cash_amount:
            rejection_reasons["below_min_trade"] += 1
            return None
        quantity = _quantize_quantity(notional / candidate.current_price)
        if quantity <= 0:
            rejection_reasons["non_positive_quantity"] += 1
            return None
        return OrderIntent(
            bot_id=context.bot.id,
            instrument_id=candidate.instrument_id,
            side=OrderSide.BUY,
            quantity=quantity,
            notional_cash=_quantize_cash(quantity * candidate.current_price),
            alpha_score=decision.alpha_score,
            confidence=decision.confidence,
            reason=decision.reason,
            request_id=self.build_request_id(
                bot_id=context.bot.id,
                ticked_at=context.as_of,
                instrument_id=candidate.instrument_id,
                side=OrderSide.BUY,
            ),
        )

    def _plan_sell_intent(
        self,
        *,
        context: BotTickContext,
        strategy_config: StrategyConfig,
        decision: StrategyDecision,
        candidate: CandidateInstrumentContext,
        requested_notional: Decimal,
        position,
        rejection_reasons: Counter[str],
    ) -> OrderIntent | None:
        if position is None or position.quantity <= 0:
            rejection_reasons["position_unavailable"] += 1
            return None
        total_equity = context.portfolio.total_equity
        max_trade_notional = _quantize_cash(
            total_equity * Decimal(str(strategy_config.risk.max_trade_cash_pct))
        )
        notional = min(
            requested_notional,
            position.market_value,
            strategy_config.risk.max_trade_cash_amount,
            max_trade_notional,
        )
        notional = _quantize_cash(notional)
        if notional < strategy_config.risk.min_trade_cash_amount:
            rejection_reasons["below_min_trade"] += 1
            return None
        quantity = min(position.quantity, _quantize_quantity(notional / candidate.current_price))
        if quantity <= 0:
            rejection_reasons["non_positive_quantity"] += 1
            return None
        return OrderIntent(
            bot_id=context.bot.id,
            instrument_id=candidate.instrument_id,
            side=OrderSide.SELL,
            quantity=quantity,
            notional_cash=_quantize_cash(quantity * candidate.current_price),
            alpha_score=decision.alpha_score,
            confidence=decision.confidence,
            reason=decision.reason,
            request_id=self.build_request_id(
                bot_id=context.bot.id,
                ticked_at=context.as_of,
                instrument_id=candidate.instrument_id,
                side=OrderSide.SELL,
            ),
        )

    def _apply_size_adjustments(
        self,
        strategy_config: StrategyConfig,
        *,
        decision: StrategyDecision,
        candidate: CandidateInstrumentContext,
        requested_notional: Decimal,
    ) -> Decimal:
        notional = requested_notional
        if (
            strategy_config.risk.reduce_size_when_confidence_below is not None
            and decision.confidence < strategy_config.risk.reduce_size_when_confidence_below
        ):
            threshold = strategy_config.risk.reduce_size_when_confidence_below
            if threshold > 0:
                confidence_ratio = max(decision.confidence / threshold, 0.2)
                notional *= Decimal(str(confidence_ratio))
        if candidate.current_holding_value > 0 and hasattr(strategy_config, "sizing"):
            penalty = getattr(strategy_config.sizing, "position_concentration_penalty", None)
            if penalty is not None:
                notional *= Decimal(str(max(0.2, 1.0 - (0.5 * penalty))))
        if strategy_config.execution.size_noise_pct > 0:
            noise_factor = 1.0 + self.random_source.uniform(
                -strategy_config.execution.size_noise_pct,
                strategy_config.execution.size_noise_pct,
            )
            notional *= Decimal(str(max(noise_factor, 0.1)))
        return _quantize_cash(notional)

    def _next_tick_after(
        self,
        as_of: datetime,
        execution: ExecutionConfig,
    ) -> datetime:
        jitter_minutes = (
            0.0
            if execution.decision_jitter_minutes <= 0
            else self.random_source.uniform(0.0, float(execution.decision_jitter_minutes))
        )
        return as_of + timedelta(minutes=execution.tick_cadence_minutes + jitter_minutes)

    def _team_exposure(self, portfolio: BotPortfolioContext) -> dict[str, Decimal]:
        exposure: dict[str, Decimal] = {}
        for position in portfolio.positions:
            if position.club is None:
                continue
            exposure[position.club] = exposure.get(position.club, Decimal("0")) + position.market_value
        return exposure

    def _apply_team_exposure(
        self,
        exposure: dict[str, Decimal],
        candidate: CandidateInstrumentContext,
        change_cash: Decimal,
    ) -> dict[str, Decimal]:
        if candidate.club is None:
            return dict(exposure)
        updated = dict(exposure)
        updated[candidate.club] = updated.get(candidate.club, Decimal("0")) + change_cash
        return updated

    def _max_player_position_pct(self, strategy_config: StrategyConfig) -> float | None:
        if strategy_config.risk.max_player_position_pct is not None:
            return strategy_config.risk.max_player_position_pct
        if isinstance(strategy_config, PortfolioRebalancerConfig):
            return strategy_config.portfolio_targets.max_player_position_pct
        return None

    def _max_team_exposure_pct(self, strategy_config: StrategyConfig) -> float | None:
        if strategy_config.risk.max_team_exposure_pct is not None:
            return strategy_config.risk.max_team_exposure_pct
        if isinstance(strategy_config, PortfolioRebalancerConfig):
            return strategy_config.portfolio_targets.max_team_exposure_pct
        return None

    def _min_cash_reserve_pct(self, strategy_config: StrategyConfig) -> float | None:
        if strategy_config.risk.min_cash_reserve_pct is not None:
            return strategy_config.risk.min_cash_reserve_pct
        if isinstance(strategy_config, PortfolioRebalancerConfig):
            return strategy_config.portfolio_targets.min_cash_pct
        return None

    def build_request_id(
        self,
        *,
        bot_id: UUID,
        ticked_at: datetime,
        instrument_id: UUID,
        side: OrderSide,
    ) -> str:
        return (
            f"synthetic-trader:{bot_id}:"
            f"{ticked_at.astimezone(UTC).isoformat()}:"
            f"{instrument_id}:{side.value}"
        )


def _quantize_quantity(value: Decimal) -> Decimal:
    return value.quantize(DECIMAL_QUANTITY_STEP, rounding=ROUND_DOWN)


def _quantize_cash(value: Decimal) -> Decimal:
    return value.quantize(DECIMAL_CASH_STEP, rounding=ROUND_DOWN)


def _format_decimal(value: Decimal, *, places: int) -> str:
    return format(value.quantize(Decimal("1").scaleb(-places), rounding=ROUND_DOWN), "f")


def _without_portfolio_holdings(
    candidates: tuple[CandidateInstrumentContext, ...],
) -> tuple[CandidateInstrumentContext, ...]:
    return tuple(
        replace(
            candidate,
            current_holding_quantity=Decimal("0"),
            current_holding_value=Decimal("0"),
        )
        for candidate in candidates
    )


def _with_portfolio_holdings(
    candidates: tuple[CandidateInstrumentContext, ...],
    portfolio: BotPortfolioContext,
) -> tuple[CandidateInstrumentContext, ...]:
    holdings = {position.instrument_id: position for position in portfolio.positions}
    return tuple(
        replace(
            candidate,
            current_holding_quantity=holdings[candidate.instrument_id].quantity
            if candidate.instrument_id in holdings
            else Decimal("0"),
            current_holding_value=holdings[candidate.instrument_id].market_value
            if candidate.instrument_id in holdings
            else Decimal("0"),
        )
        for candidate in candidates
    )
