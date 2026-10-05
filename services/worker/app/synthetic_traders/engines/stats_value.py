from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from math import log10

from app.synthetic_traders.config import StatsValueConfig
from app.synthetic_traders.config_models import StatsInputsConfig
from app.synthetic_traders.models import (
    BotTickContext,
    DecisionSide,
    PlayerStatsContext,
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

# Per-90 levels treated as the top of the scale, about the 95th percentile of Premier League
# regulars in 2025-26 FBref data.
ELITE_GOALS_PER90 = 0.5
ELITE_ASSISTS_PER90 = 0.3
ELITE_SHOTS_PER90 = 3.0
ELITE_KEY_PASSES_PER90 = 2.0
ELITE_DEFENSIVE_ACTIONS_PER90 = 3.0
ELITE_CLEAN_SHEETS_PER_GAME = 0.45
ELITE_CARDS_PER90 = 0.5
# Change in per-90 output between recent matches and the season that counts as full form.
FORM_GOAL_INVOLVEMENT_SWING = 0.4
FORM_DEFENSIVE_SWING = 1.5


@dataclass(frozen=True)
class StatsValueStrategyEngine:
    strategy_engine: StrategyEngine = StrategyEngine.STATS_VALUE

    def evaluate(
        self,
        context: BotTickContext,
        config: StatsValueConfig,
    ) -> tuple[StrategyDecision, ...]:
        # Filter stale evidence before sampling so it cannot crowd out fresh candidates.
        candidates = filter_candidates(
            tuple(
                c
                for c in context.candidates
                if c.stats.latest_observed_at is None
                or context.as_of - c.stats.latest_observed_at <= timedelta(days=30)
            ),
            config.universe,
            f"{context.bot.id}:{context.as_of.date()}",
        )
        if not candidates:
            return ()

        candidates = [
            replace(c, market_value_observation=None)
            if c.market_value_observed_at is not None
            and context.as_of - c.market_value_observed_at
            > timedelta(days=config.lookbacks.market_value_days)
            else c
            for c in candidates
        ]
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
        if config.stats_inputs.position_baseline_enabled:
            groups = {}
            for c in candidates:
                position = (canonical_position_codes(c.position) or ("UNKNOWN",))[0]
                groups.setdefault(position, {})[c.instrument_id] = performance_raw[c.instrument_id]
            performance_rank = {
                key: score
                for group in groups.values()
                for key, score in rank_percentiles(group).items()
            }
        market_value_rank = rank_percentiles(market_value_raw)
        price_rank = rank_percentiles(price_raw)
        momentum_window_start = context.as_of - timedelta(days=config.lookbacks.price_momentum_days)
        volatility_window_start = context.as_of - timedelta(
            days=max(config.lookbacks.price_momentum_days, 7)
        )

        decisions: list[StrategyDecision] = []
        for candidate in candidates:
            stats_form = performance_rank.get(candidate.instrument_id, 0.5) * 2.0 - 1.0
            minutes_security = clamp(
                ((candidate.stats.minutes_per_game or 0.0) / 90.0) * 2.0 - 1.0,
                -1.0,
                1.0,
            )
            market_rank = market_value_rank.get(
                candidate.instrument_id, performance_rank.get(candidate.instrument_id, 0.5)
            )
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
            position_adjustment = (
                stats_form if config.stats_inputs.position_baseline_enabled else 0.0
            )
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
            if candidate.stats.games == 0:
                availability_risk = 1.0
            elif (
                candidate.stats.minutes_per_game is not None
                and candidate.stats.minutes_per_game < 45
            ):
                availability_risk = 0.6
            social_confirmation = clamp(candidate.social.sentiment_score, -1.0, 1.0)
            alpha = (
                config.signal_weights.get("stats_form", 0.0) * stats_form
                + config.signal_weights.get("minutes_security", 0.0) * minutes_security
                + config.signal_weights.get("market_value_gap", 0.0) * market_value_gap
                + config.signal_weights.get("fixture_context", 0.0) * candidate.fixture_score
                + config.signal_weights.get("position_adjustment", 0.0) * position_adjustment
                + config.signal_weights.get("stockball_price_momentum", 0.0)
                * clamp(price_momentum / 0.15, -1.0, 1.0)
                + config.signal_weights.get("social_confirmation", 0.0) * social_confirmation
                + config.signal_weights.get("availability_risk", 0.0) * availability_risk
                + config.signal_weights.get("volatility_risk", 0.0) * volatility_risk
            )
            confidence = clamp(
                min(candidate.stats.games / max(config.lookbacks.form_matches, 1), 1.0) * 0.5
                + (0.25 if candidate.market_value_observation is not None else 0.0)
                + min(abs(valuation_gap) * 1.5, 0.25),
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
                    and valuation_gap >= config.valuation.min_valuation_gap_to_buy
                ):
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
                        "fixture_context": candidate.fixture_score,
                        "form_weight": config.stats_inputs.form_weight,
                        "performance_score": performance_raw[candidate.instrument_id],
                        "minutes_security": minutes_security,
                        "market_value_gap": market_value_gap,
                        "availability_risk": availability_risk,
                        "volatility_risk": volatility_risk,
                    },
                )
            )

        return sorted_decisions(decisions)

    def _performance_score(self, candidate, config: StatsValueConfig) -> float:
        """How good the player's per-90 output is to this bot, from 0 to 1.

        A weighted average over the stats that apply to the player, so a bot that cares mostly
        about defending and one that cares mostly about goals rank players differently. Stats
        the provider doesn't supply (chance creation, match ratings) are left out rather than
        counted as zero.
        """
        stats = candidate.stats
        inputs = config.stats_inputs
        if stats.games <= 0 and stats.minutes_per_game is None:
            return 0.0
        components = [
            (inputs.goals_weight, clamp(stats.goals_per90 / ELITE_GOALS_PER90, 0.0, 1.0)),
            (inputs.assists_weight, clamp(stats.assists_per90 / ELITE_ASSISTS_PER90, 0.0, 1.0)),
            (inputs.shots_weight, clamp(stats.shots_per90 / ELITE_SHOTS_PER90, 0.0, 1.0)),
            (
                inputs.defensive_actions_weight,
                clamp(stats.defensive_actions_per90 / ELITE_DEFENSIVE_ACTIONS_PER90, 0.0, 1.0),
            ),
            (inputs.minutes_weight, clamp((stats.minutes_per_game or 0.0) / 90.0, 0.0, 1.0)),
        ]
        if stats.available_rates is not None:
            components = [
                component
                for name, component in zip(
                    ("goals", "assists", "shots", "defensive_actions", "minutes"), components
                )
                if name == "minutes" or name in stats.available_rates
            ]
        if stats.available_rates is None or "key_passes" in stats.available_rates:
            components.append(
                (
                    inputs.key_passes_weight,
                    clamp(stats.key_passes_per90 / ELITE_KEY_PASSES_PER90, 0.0, 1.0),
                )
            )
        if stats.clean_sheets_per_game is not None:
            components.append(
                (
                    inputs.clean_sheet_weight,
                    clamp(stats.clean_sheets_per_game / ELITE_CLEAN_SHEETS_PER_GAME, 0.0, 1.0),
                )
            )
        if stats.average_rating is not None:
            components.append(
                (inputs.rating_weight, clamp((stats.average_rating - 6.0) / 2.5, 0.0, 1.0))
            )
        form = form_score(stats, inputs)
        if form is not None:
            components.append((inputs.form_weight, (form + 1.0) / 2.0))
        total_weight = sum(max(weight, 0.0) for weight, _ in components)
        if total_weight <= 0:
            return 0.0
        quality = sum(max(weight, 0.0) * score for weight, score in components) / total_weight
        # cards_penalty_weight is negative in every profile, so bookings lower the score.
        return quality + inputs.cards_penalty_weight * clamp(
            stats.cards_per90 / ELITE_CARDS_PER90, 0.0, 1.0
        )


def form_score(stats: PlayerStatsContext, inputs: StatsInputsConfig) -> float | None:
    """-1..1: recent output against the season so far, judged on what this bot values.

    Attacking form (goal involvements) and defensive form count in proportion to how much the
    bot weights attacking and defensive stats. None until there is enough recent football.
    """
    attack_weight = max(inputs.goals_weight + inputs.assists_weight + inputs.shots_weight, 0.0)
    defence_weight = max(inputs.defensive_actions_weight + inputs.clean_sheet_weight, 0.0)
    parts: list[tuple[float, float]] = []
    if stats.recent_goal_involvements_per90 is not None:
        season = stats.goals_per90 + stats.assists_per90
        parts.append(
            (
                attack_weight,
                clamp(
                    (stats.recent_goal_involvements_per90 - season) / FORM_GOAL_INVOLVEMENT_SWING,
                    -1.0,
                    1.0,
                ),
            )
        )
    if stats.recent_defensive_actions_per90 is not None:
        parts.append(
            (
                defence_weight,
                clamp(
                    (stats.recent_defensive_actions_per90 - stats.defensive_actions_per90)
                    / FORM_DEFENSIVE_SWING,
                    -1.0,
                    1.0,
                ),
            )
        )
    total = sum(weight for weight, _ in parts)
    if not parts or total <= 0:
        return None
    return sum(weight * score for weight, score in parts) / total
