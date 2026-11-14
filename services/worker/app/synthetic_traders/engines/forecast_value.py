from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.player_stats import RATING_PRIOR_NINETIES
from app.synthetic_traders.config import ForecastValueConfig
from app.synthetic_traders.models import (
    BotTickContext,
    CandidateInstrumentContext,
    DecisionSide,
    StrategyDecision,
    StrategyEngine,
)

from .base import (
    clamp,
    filter_candidates,
    price_change_pct,
    rank_percentiles,
    sorted_decisions,
    stats_confirmation,
)


@dataclass(frozen=True)
class ForecastValueStrategyEngine:
    """Trades where a player's rating is expected to go, not where it is.

    The stats engines price a player's steadied season rating. This engine reads the active
    forecast model's expected change from that rating over the profile's horizon (his next
    match, or a longer run) and buys players expected to improve and sells holdings expected
    to decline. A Stockball price that has already moved the same way counts as priced in.

    Players without a fresh forecast for the horizon are not candidates, so with no active
    model, or one that failed to beat the baseline at this horizon, the engine holds.
    """

    strategy_engine: StrategyEngine = StrategyEngine.FORECAST_VALUE

    def evaluate(
        self,
        context: BotTickContext,
        config: ForecastValueConfig,
    ) -> tuple[StrategyDecision, ...]:
        inputs = config.forecast_inputs
        as_of = _as_utc(context.as_of)
        max_age = timedelta(hours=inputs.max_forecast_age_hours)

        def expected_change(candidate: CandidateInstrumentContext) -> float | None:
            forecast = candidate.forecast
            if (
                forecast is None
                or forecast.history_nineties < inputs.min_history_nineties
                or not timedelta(0) <= as_of - _as_utc(forecast.as_of) <= max_age
            ):
                return None
            return forecast.expected_change.get(inputs.horizon_matches)

        candidates = filter_candidates(
            tuple(c for c in context.candidates if expected_change(c) is not None),
            config.universe,
            f"{context.bot.id}:{context.as_of.date()}",
        )
        if not candidates:
            return ()
        changes = {c.instrument_id: expected_change(c) or 0.0 for c in candidates}
        ranks = rank_percentiles(changes)
        momentum_start = context.as_of - timedelta(days=config.lookbacks.price_momentum_days)
        weights = config.signal_weights

        decisions: list[StrategyDecision] = []
        for candidate in candidates:
            forecast = candidate.forecast
            assert forecast is not None
            change = changes[candidate.instrument_id]
            signal = clamp(change / inputs.change_scale, -1.0, 1.0)
            rank = ranks.get(candidate.instrument_id, 0.5) * 2.0 - 1.0
            direction = 1.0 if signal > 0 else -1.0 if signal < 0 else 0.0
            price_move = price_change_pct(
                candidate.recent_prices, candidate.current_price, momentum_start
            )
            already_moved = max(
                clamp(price_move / inputs.priced_in_move_pct, -1.0, 1.0) * direction, 0.0
            )
            alpha = (
                weights.get("expected_change", 0.0) * signal
                + weights.get("change_rank", 0.0) * rank
                # The weight is negative: a move already made shrinks the forecast's edge.
                + direction * weights.get("price_already_moved", 0.0) * already_moved
                + weights.get("season_quality", 0.0) * stats_confirmation(candidate.stats)
            )
            reliability = forecast.history_nineties / (
                forecast.history_nineties + RATING_PRIOR_NINETIES
            )
            confidence = clamp(0.3 + 0.4 * reliability + 0.3 * abs(signal), 0.0, 1.0)
            side = DecisionSide.HOLD
            if abs(alpha) > config.decision.hold_band and (
                confidence >= config.decision.min_confidence
            ):
                if alpha >= config.decision.buy_threshold:
                    side = DecisionSide.BUY
                elif (
                    config.decision.allow_sells
                    and candidate.current_holding_quantity > 0
                    and alpha <= config.decision.sell_threshold
                ):
                    side = DecisionSide.SELL
            decisions.append(
                StrategyDecision(
                    instrument_id=candidate.instrument_id,
                    side=side,
                    alpha_score=alpha,
                    expected_return=signal,
                    confidence=confidence,
                    suggested_cash_pct=config.sizing.base_cash_pct
                    * (
                        1.0
                        + config.sizing.confidence_multiplier * confidence
                        + config.sizing.expected_return_multiplier * abs(signal)
                    ),
                    reason={
                        "engine": self.strategy_engine.value,
                        "horizon_matches": inputs.horizon_matches,
                        "baseline_rating": forecast.baseline_rating,
                        "expected_change": change,
                        "change_signal": signal,
                        "change_rank": rank,
                        "price_move": price_move,
                        "price_already_moved": already_moved,
                        "history_nineties": forecast.history_nineties,
                        "forecast_as_of": forecast.as_of.isoformat(),
                    },
                )
            )
        return sorted_decisions(decisions)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
