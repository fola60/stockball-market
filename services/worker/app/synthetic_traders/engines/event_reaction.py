from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from statistics import fmean
from typing import Mapping
from uuid import UUID

from app.player_stats import MATCH_RATING_SD, RATING_PRIOR_NINETIES
from app.synthetic_traders.config import EventReactionConfig
from app.synthetic_traders.config_models import EventReactionInputsConfig
from app.synthetic_traders.models import (
    BettingMarketQuote,
    BotTickContext,
    CandidateInstrumentContext,
    DecisionSide,
    MatchEventContext,
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
from .betting_market_value import (
    _as_utc,
    _comparable_selection,
    _nearest_event_quotes,
    _normalized_probability,
)


@dataclass(frozen=True)
class EventReactionStrategyEngine:
    """Trades the surprise in a player's latest FotMob-rated match.

    A match rating is judged against the player's steadied rating before the match, in units
    of one match's typical deviation. Bookmakers' closing quotes say how involved the player
    was expected to be: a big game from an outsider is a bigger surprise than one from the
    favourite, and a favourite's flop is a bigger disappointment. Movement in the next
    fixture's odds since then confirms or contradicts the reaction, and a Stockball price that
    has already moved the same way counts as priced in.

    The signal fades with a half-life. Each bot waits its own reaction delay, jittered per
    match, so a fleet does not trade on the same whistle in the same minute. A position the bot
    itself traded is unwound once the holding period has passed since that trade; positions it
    was only allocated are left alone, since they were never a reaction.
    """

    strategy_engine: StrategyEngine = StrategyEngine.EVENT_REACTION

    def evaluate(
        self,
        context: BotTickContext,
        config: EventReactionConfig,
    ) -> tuple[StrategyDecision, ...]:
        as_of = _as_utc(context.as_of)
        window = timedelta(hours=config.lookbacks.event_window_hours)

        def has_event(candidate: CandidateInstrumentContext) -> bool:
            event = candidate.match_event
            return event is not None and timedelta(0) <= as_of - _as_utc(event.known_at) <= window

        traded_at = {
            position.instrument_id: _as_utc(position.last_trade_at)
            for position in context.portfolio.positions
            if position.last_trade_at is not None and position.quantity > 0
        }
        candidates = filter_candidates(
            tuple(c for c in context.candidates if has_event(c) or c.instrument_id in traded_at),
            config.universe,
            f"{context.bot.id}:{context.as_of.date()}",
        )
        if not candidates:
            return ()
        expectations = _expectation_ranks(
            [c for c in candidates if has_event(c)], config.event_inputs
        )
        holding_period = timedelta(hours=config.event_inputs.holding_period_hours)

        decisions: list[StrategyDecision] = []
        for candidate in candidates:
            decision = (
                self._react(context, config, candidate, expectations)
                if has_event(candidate)
                else None
            )
            last_trade_at = traded_at.get(candidate.instrument_id)
            # A fresh match still inside its reaction delay gets considered before any exit.
            if (
                config.decision.allow_sells
                and last_trade_at is not None
                and as_of - last_trade_at >= holding_period
                and (decision is None or decision.reason["action"] == "hold")
            ):
                decision = self._unwind(context, config, candidate, last_trade_at, decision)
            if decision is not None:
                decisions.append(decision)
        return sorted_decisions(decisions)

    def _react(
        self,
        context: BotTickContext,
        config: EventReactionConfig,
        candidate: CandidateInstrumentContext,
        expectations: Mapping[UUID, float],
    ) -> StrategyDecision:
        inputs = config.event_inputs
        event = candidate.match_event
        assert event is not None
        as_of = _as_utc(context.as_of)
        age_hours = (as_of - _as_utc(event.known_at)).total_seconds() / 3600.0
        delay_minutes = inputs.reaction_delay_minutes * (
            0.5 + _unit_hash(context.bot.id, event.provider_match_id)
        )
        minutes_share = min(event.minutes_played / 90.0, 1.0)
        rating_z = (event.rating - event.baseline_rating) / MATCH_RATING_SD
        surprise = (
            clamp(rating_z / inputs.surprise_scale, -1.0, 1.0) * minutes_share
            if event.minutes_played >= inputs.min_minutes
            else 0.0
        )
        expectation = expectations.get(candidate.instrument_id)
        # Positive expectation (a heavily backed player) shrinks a good surprise and deepens a
        # bad one; an outsider's surprise works the other way.
        match_surprise = (
            surprise
            if expectation is None
            else clamp(
                surprise - inputs.expectation_weight * expectation * abs(surprise), -1.0, 1.0
            )
        )
        freshness = 0.5 ** (age_hours / inputs.half_life_hours)
        odds_movement = _next_match_movement(candidate, as_of, inputs)
        direction = 1.0 if match_surprise > 0 else -1.0 if match_surprise < 0 else 0.0
        price_move = price_change_pct(
            candidate.recent_prices, candidate.current_price, _as_utc(event.known_at)
        )
        already_moved = max(
            clamp(price_move / inputs.priced_in_move_pct, -1.0, 1.0) * direction, 0.0
        )
        weights = config.signal_weights
        alpha = (
            freshness
            * (
                weights.get("match_surprise", 0.0) * match_surprise
                + weights.get("next_match_odds_movement", 0.0) * (odds_movement or 0.0)
            )
            # The weight is negative: a move already made shrinks the reaction.
            + direction * weights.get("price_already_moved", 0.0) * already_moved
            + weights.get("season_quality", 0.0) * stats_confirmation(candidate.stats)
        )
        baseline_reliability = event.baseline_nineties / (
            event.baseline_nineties + RATING_PRIOR_NINETIES
        )
        confidence = clamp(
            0.2
            + 0.3 * minutes_share
            + 0.2 * baseline_reliability
            + (0.15 if expectation is not None else 0.0)
            + (0.15 if odds_movement is not None else 0.0),
            0.0,
            1.0,
        )
        side = DecisionSide.HOLD
        action = "hold"
        if age_hours * 60.0 < delay_minutes:
            action = "awaiting_reaction_delay"
        elif abs(alpha) > config.decision.hold_band and confidence >= config.decision.min_confidence:
            if alpha >= config.decision.buy_threshold:
                side, action = DecisionSide.BUY, "react"
            elif (
                config.decision.allow_sells
                and candidate.current_holding_quantity > 0
                and alpha <= config.decision.sell_threshold
            ):
                side, action = DecisionSide.SELL, "react"
        return StrategyDecision(
            instrument_id=candidate.instrument_id,
            side=side,
            alpha_score=alpha,
            expected_return=match_surprise * freshness,
            confidence=confidence,
            suggested_cash_pct=config.sizing.base_cash_pct
            * (
                1.0
                + config.sizing.confidence_multiplier * confidence
                + config.sizing.surprise_multiplier * abs(match_surprise)
            ),
            reason={
                "engine": self.strategy_engine.value,
                "action": action,
                "provider_match_id": event.provider_match_id,
                "opponent": event.opponent_name,
                "rating": event.rating,
                "baseline_rating": event.baseline_rating,
                "minutes_played": event.minutes_played,
                "rating_z": rating_z,
                "match_surprise": match_surprise,
                "betting_expectation": expectation,
                "next_match_odds_movement": odds_movement,
                "price_move_since_event": price_move,
                "freshness": freshness,
                "event_age_hours": age_hours,
                "reaction_delay_minutes": delay_minutes,
            },
        )

    def _unwind(
        self,
        context: BotTickContext,
        config: EventReactionConfig,
        candidate: CandidateInstrumentContext,
        last_trade_at: datetime,
        reaction: StrategyDecision | None,
    ) -> StrategyDecision:
        equity = float(context.portfolio.total_equity)
        reason = dict(reaction.reason) if reaction is not None else {
            "engine": self.strategy_engine.value
        }
        reason["action"] = "unwind"
        reason["hours_since_last_trade"] = (
            _as_utc(context.as_of) - last_trade_at
        ).total_seconds() / 3600.0
        return StrategyDecision(
            instrument_id=candidate.instrument_id,
            side=DecisionSide.SELL,
            alpha_score=min(
                reaction.alpha_score if reaction is not None else 0.0,
                config.decision.sell_threshold,
            ),
            expected_return=0.0,
            # A mechanical exit, not a forecast.
            confidence=1.0,
            suggested_cash_pct=(
                float(candidate.current_holding_value) / equity * config.event_inputs.unwind_fraction
                if equity > 0
                else 0.0
            ),
            reason=reason,
        )


def _expectation_ranks(
    candidates: list[CandidateInstrumentContext],
    inputs: EventReactionInputsConfig,
) -> dict[UUID, float]:
    """-1..1: how involved bookmakers expected each player to be in his rated match.

    Closing probabilities are ranked per market type across the players with quotes, then
    averaged with the configured market weights. Players without closing quotes are absent.
    """
    by_type: dict[str, dict[UUID, float]] = {}
    for candidate in candidates:
        event = candidate.match_event
        if event is None:
            continue
        for market_type, probability in _closing_probabilities(event, inputs).items():
            by_type.setdefault(market_type, {})[candidate.instrument_id] = probability
    ranks = {market_type: rank_percentiles(values) for market_type, values in by_type.items()}
    weighted: dict[UUID, list[tuple[float, float]]] = {}
    for market_type, values in ranks.items():
        for instrument_id, rank in values.items():
            weighted.setdefault(instrument_id, []).append(
                (rank * 2.0 - 1.0, inputs.market_type_weights[market_type])
            )
    return {
        instrument_id: sum(rank * weight for rank, weight in items)
        / sum(weight for _, weight in items)
        for instrument_id, items in weighted.items()
    }


def _closing_probabilities(
    event: MatchEventContext, inputs: EventReactionInputsConfig
) -> dict[str, float]:
    quotes = [
        quote
        for quote in event.closing_quotes
        if quote.market_type in inputs.market_type_weights and _comparable_selection(quote)
    ]
    by_type: dict[str, list[float]] = {}
    for quote in quotes:
        by_type.setdefault(quote.market_type, []).append(
            _normalized_probability(quote, list(event.closing_quotes))
        )
    return {market_type: fmean(values) for market_type, values in by_type.items()}


def _next_match_movement(
    candidate: CandidateInstrumentContext,
    as_of: datetime,
    inputs: EventReactionInputsConfig,
) -> float | None:
    """-1..1: how the player's odds for his next fixture have moved over the betting window.

    None without at least two observations of a comparable selection.
    """
    upcoming = [
        quote
        for quote in candidate.betting.quotes
        if quote.market_type in inputs.market_type_weights
        and quote.kickoff_at is not None
        and _as_utc(quote.kickoff_at) > as_of
        and _as_utc(quote.observed_at) <= as_of
        and _comparable_selection(quote)
    ]
    event_quotes = _nearest_event_quotes(upcoming, as_of)
    by_selection: dict[str, list[BettingMarketQuote]] = {}
    for quote in event_quotes:
        by_selection.setdefault(quote.canonical_selection_key, []).append(quote)
    movements: list[tuple[float, float]] = []
    for quotes in by_selection.values():
        ordered = sorted(quotes, key=lambda quote: _as_utc(quote.observed_at))
        if len({quote.observed_at for quote in ordered}) < 2:
            continue
        first = _normalized_probability(ordered[0], event_quotes)
        last = _normalized_probability(ordered[-1], event_quotes)
        if first <= 0:
            continue
        movements.append(
            (
                clamp(((last - first) / first) / inputs.movement_scale, -1.0, 1.0),
                inputs.market_type_weights[ordered[-1].market_type],
            )
        )
    if not movements:
        return None
    return sum(value * weight for value, weight in movements) / sum(
        weight for _, weight in movements
    )


def _unit_hash(bot_id: UUID, match_id: str) -> float:
    """A stable 0..1 draw per bot and match, spreading reaction times across a fleet."""
    digest = sha256(f"{bot_id}:{match_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)

