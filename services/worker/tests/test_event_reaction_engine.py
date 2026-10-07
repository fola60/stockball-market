from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.synthetic_traders import (
    BettingMarketContext,
    BettingMarketQuote,
    BotPositionContext,
    BotStatus,
    DecisionSide,
    MatchEventContext,
    PlayerStatsContext,
    StrategyEngine,
    SyntheticTraderBotRecord,
    parse_strategy_config,
)
from app.synthetic_traders.engines import EventReactionStrategyEngine, StatsValueStrategyEngine
from app.synthetic_traders.engines.base import stats_confirmation
from tests.test_synthetic_trader_configs import _event_reaction_payload, _stats_value_payload
from tests.test_synthetic_trader_engines import _candidate, _context

AS_OF = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)


def _event(
    *,
    rating: float = 8.6,
    baseline: float = 7.0,
    minutes: int = 90,
    known_hours_ago: float = 4.0,
    closing_probability: Decimal | None = None,
) -> MatchEventContext:
    known_at = AS_OF - timedelta(hours=known_hours_ago)
    kickoff_at = known_at - timedelta(hours=2, minutes=15)
    quotes = ()
    if closing_probability is not None:
        quotes = (
            BettingMarketQuote(
                provider_event_id="past-event",
                canonical_selection_key="SCORE_OR_ASSIST|FULL_MATCH|ANYTIME|1|player",
                market_type="SCORE_OR_ASSIST",
                outcome_type="ANYTIME",
                line=Decimal("1"),
                decimal_odds=Decimal("1") / closing_probability,
                implied_probability=closing_probability,
                observed_at=kickoff_at - timedelta(minutes=5),
                kickoff_at=kickoff_at,
            ),
        )
    return MatchEventContext(
        provider_match_id="4813377",
        kickoff_at=kickoff_at,
        known_at=known_at,
        rating=rating,
        minutes_played=minutes,
        baseline_rating=baseline,
        baseline_nineties=12.0,
        closing_quotes=quotes,
    )


def _next_fixture(previous: Decimal, current: Decimal) -> BettingMarketContext:
    kickoff = AS_OF + timedelta(days=4)
    return BettingMarketContext(
        quotes=tuple(
            BettingMarketQuote(
                provider_event_id="next-event",
                canonical_selection_key="SCORE_OR_ASSIST|FULL_MATCH|ANYTIME|1|player",
                market_type="SCORE_OR_ASSIST",
                outcome_type="ANYTIME",
                line=Decimal("1"),
                decimal_odds=Decimal("1") / probability,
                implied_probability=probability,
                observed_at=observed_at,
                kickoff_at=kickoff,
                observation_count=2,
            )
            for observed_at, probability in (
                (AS_OF - timedelta(hours=8), previous),
                (AS_OF - timedelta(minutes=10), current),
            )
        )
    )


class EventReactionEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bot = SyntheticTraderBotRecord(
            id=uuid4(),
            account_id=uuid4(),
            portfolio_id=uuid4(),
            config_id=uuid4(),
            bot_key="reactor",
            display_name="Reactor",
            status=BotStatus.ACTIVE,
            config_overrides={},
            last_ticked_at=None,
            next_tick_after=None,
            created_at=AS_OF,
            updated_at=AS_OF,
        )
        self.engine = EventReactionStrategyEngine()

    def _config(self, **event_inputs):
        payload = copy.deepcopy(_event_reaction_payload())
        payload["event_inputs"].update(event_inputs)
        return parse_strategy_config(StrategyEngine.EVENT_REACTION, payload)

    def _decide(self, *candidates, config=None):
        decisions = self.engine.evaluate(
            _context(self.bot, candidates=tuple(candidates)), config or self._config()
        )
        return {decision.instrument_id: decision for decision in decisions}

    def _flat(self, **kwargs):
        # Flat recent prices: nothing priced in yet.
        return _candidate(
            recent_price_values=(Decimal("20"), Decimal("20"), Decimal("20")),
            current_price=Decimal("20"),
            **kwargs,
        )

    def test_buys_a_big_game_confirmed_by_the_next_fixture_odds(self) -> None:
        candidate = replace(
            self._flat(betting=_next_fixture(Decimal("0.30"), Decimal("0.36"))),
            match_event=_event(closing_probability=Decimal("0.25")),
        )
        decision = self._decide(candidate)[candidate.instrument_id]

        self.assertIs(decision.side, DecisionSide.BUY)
        self.assertEqual(decision.reason["action"], "react")
        self.assertGreater(decision.reason["next_match_odds_movement"], 0)
        self.assertGreaterEqual(decision.confidence, 0.6)

    def test_ignores_players_without_a_rated_match(self) -> None:
        self.assertEqual(self._decide(self._flat()), {})

    def test_waits_for_its_reaction_delay(self) -> None:
        candidate = replace(self._flat(), match_event=_event(known_hours_ago=0.25))
        decision = self._decide(candidate)[candidate.instrument_id]

        self.assertIs(decision.side, DecisionSide.HOLD)
        self.assertEqual(decision.reason["action"], "awaiting_reaction_delay")

    def test_reaction_delays_differ_between_bots(self) -> None:
        candidate = replace(self._flat(), match_event=_event())
        delays = set()
        for _ in range(5):
            self.bot = replace(self.bot, id=uuid4())
            decision = self._decide(candidate)[candidate.instrument_id]
            delays.add(round(decision.reason["reaction_delay_minutes"], 3))
        self.assertGreater(len(delays), 1)

    def test_a_cameo_is_not_a_surprise(self) -> None:
        candidate = replace(self._flat(), match_event=_event(rating=6.2, minutes=20))
        decision = self._decide(candidate)[candidate.instrument_id]

        self.assertEqual(decision.reason["match_surprise"], 0.0)
        self.assertIs(decision.side, DecisionSide.HOLD)

    def test_an_outsiders_big_game_beats_the_favourites(self) -> None:
        outsider = replace(
            self._flat(), match_event=_event(closing_probability=Decimal("0.10"))
        )
        favourite = replace(
            self._flat(), match_event=_event(closing_probability=Decimal("0.60"))
        )
        decisions = self._decide(outsider, favourite)

        self.assertGreater(
            decisions[outsider.instrument_id].reason["match_surprise"],
            decisions[favourite.instrument_id].reason["match_surprise"],
        )
        self.assertLess(decisions[favourite.instrument_id].reason["betting_expectation"], 1.01)

    def test_a_favourites_flop_is_a_deeper_disappointment(self) -> None:
        outsider = replace(
            self._flat(), match_event=_event(rating=5.6, closing_probability=Decimal("0.10"))
        )
        favourite = replace(
            self._flat(), match_event=_event(rating=5.6, closing_probability=Decimal("0.60"))
        )
        decisions = self._decide(outsider, favourite)

        self.assertLess(
            decisions[favourite.instrument_id].reason["match_surprise"],
            decisions[outsider.instrument_id].reason["match_surprise"],
        )

    def test_a_price_that_already_moved_is_priced_in(self) -> None:
        fresh = replace(self._flat(), match_event=_event(known_hours_ago=4.5))
        moved = replace(
            _candidate(
                recent_price_values=(Decimal("20"), Decimal("21"), Decimal("23")),
                current_price=Decimal("23"),
            ),
            match_event=_event(known_hours_ago=4.5),
        )
        decisions = self._decide(fresh, moved)

        self.assertLess(
            decisions[moved.instrument_id].alpha_score,
            decisions[fresh.instrument_id].alpha_score,
        )

    def test_sells_a_held_player_after_a_poor_game(self) -> None:
        candidate = replace(
            self._flat(holding_quantity=Decimal("5")),
            match_event=_event(rating=5.4, closing_probability=Decimal("0.5")),
        )
        decision = self._decide(candidate)[candidate.instrument_id]

        self.assertIs(decision.side, DecisionSide.SELL)
        self.assertEqual(decision.reason["action"], "react")

    def test_never_sells_what_it_does_not_hold(self) -> None:
        candidate = replace(self._flat(), match_event=_event(rating=5.4))
        decision = self._decide(candidate)[candidate.instrument_id]

        self.assertIsNot(decision.side, DecisionSide.SELL)

    def _decide_holding(self, candidate, last_trade_at):
        position = BotPositionContext(
            instrument_id=candidate.instrument_id,
            player_id=candidate.player_id,
            club=candidate.club,
            quantity=candidate.current_holding_quantity,
            current_price=candidate.current_price,
            market_value=candidate.current_holding_value,
            last_trade_at=last_trade_at,
        )
        context = _context(self.bot, candidates=(candidate,))
        context = replace(context, portfolio=replace(context.portfolio, positions=(position,)))
        decisions = self.engine.evaluate(context, self._config())
        return {decision.instrument_id: decision for decision in decisions}

    def test_unwinds_its_own_trade_after_the_holding_period(self) -> None:
        candidate = replace(
            self._flat(holding_quantity=Decimal("10")),
            match_event=_event(rating=7.1, known_hours_ago=36.0),
        )
        decision = self._decide_holding(candidate, AS_OF - timedelta(hours=31))[
            candidate.instrument_id
        ]

        self.assertIs(decision.side, DecisionSide.SELL)
        self.assertEqual(decision.reason["action"], "unwind")
        # Half of a 200 position in a 1000 portfolio.
        self.assertAlmostEqual(decision.suggested_cash_pct, 0.1)

    def test_unwinds_once_the_event_has_left_the_window(self) -> None:
        candidate = self._flat(holding_quantity=Decimal("10"))
        decision = self._decide_holding(candidate, AS_OF - timedelta(hours=60))[
            candidate.instrument_id
        ]

        self.assertEqual(decision.reason["action"], "unwind")

    def test_never_dumps_an_allocated_position_after_a_great_game(self) -> None:
        # Seen on real data: a bootstrap holding sold right after an 8.5, purely on time.
        candidate = replace(
            self._flat(holding_quantity=Decimal("10")),
            match_event=_event(rating=8.5, known_hours_ago=40.0),
        )
        decision = self._decide_holding(candidate, None)[candidate.instrument_id]

        self.assertIsNot(decision.side, DecisionSide.SELL)

    def test_keeps_a_recent_trade(self) -> None:
        candidate = replace(
            self._flat(holding_quantity=Decimal("10")),
            match_event=_event(rating=7.1, known_hours_ago=10.0),
        )
        decision = self._decide_holding(candidate, AS_OF - timedelta(hours=8))[
            candidate.instrument_id
        ]

        self.assertIs(decision.side, DecisionSide.HOLD)

    def test_a_new_match_is_considered_before_unwinding(self) -> None:
        candidate = replace(
            self._flat(holding_quantity=Decimal("10")),
            match_event=_event(known_hours_ago=0.2),
        )
        decision = self._decide_holding(candidate, AS_OF - timedelta(hours=40))[
            candidate.instrument_id
        ]

        self.assertEqual(decision.reason["action"], "awaiting_reaction_delay")

    def test_events_outside_the_window_are_ignored(self) -> None:
        candidate = replace(self._flat(), match_event=_event(known_hours_ago=49.0))
        self.assertEqual(self._decide(candidate), {})

    def test_the_signal_fades(self) -> None:
        early = replace(self._flat(), match_event=_event(known_hours_ago=4.0))
        late = replace(self._flat(), match_event=_event(known_hours_ago=24.0))
        decisions = self._decide(early, late)

        self.assertGreater(
            decisions[early.instrument_id].alpha_score, decisions[late.instrument_id].alpha_score
        )


class RatingScoreTests(unittest.TestCase):
    def test_confirmation_blends_rating_with_per90_strength(self) -> None:
        stats = PlayerStatsContext(strength=0.2, rating_strength=0.8)
        self.assertAlmostEqual(stats_confirmation(stats), 0.5)
        self.assertAlmostEqual(stats_confirmation(PlayerStatsContext(strength=0.2)), 0.2)
        self.assertEqual(stats_confirmation(PlayerStatsContext()), 0.0)

    def test_a_lone_rating_uses_the_regulars_distribution(self) -> None:
        # 7.38 was the 95th percentile of 2025-26 regulars; a linear 0-10 scale put it near 0.4.
        self.assertGreater(stats_confirmation(PlayerStatsContext(average_rating=7.38)), 0.9)
        self.assertLess(stats_confirmation(PlayerStatsContext(average_rating=6.5)), -0.9)

    def test_stats_value_prefers_the_better_rated_of_equal_producers(self) -> None:
        config = parse_strategy_config(StrategyEngine.STATS_VALUE, _stats_value_payload())
        base = PlayerStatsContext(games=10, minutes_per_game=85.0, goals_per90=0.3)
        strong = _candidate(stats=replace(base, rating_strength=0.9))
        weak = _candidate(stats=replace(base, rating_strength=-0.9))
        engine = StatsValueStrategyEngine()
        context = _context(_any_bot(), candidates=(strong, weak))
        decisions = {d.instrument_id: d for d in engine.evaluate(context, config)}

        self.assertGreater(
            decisions[strong.instrument_id].reason["performance_score"],
            decisions[weak.instrument_id].reason["performance_score"],
        )

    def test_a_player_rated_before_fbref_lists_him_is_still_judged(self) -> None:
        config = parse_strategy_config(StrategyEngine.STATS_VALUE, _stats_value_payload())
        rated_only = _candidate(
            stats=PlayerStatsContext(
                available_rates=frozenset(), rating_strength=0.8, rated_nineties=6.0
            )
        )
        decision = StatsValueStrategyEngine().evaluate(
            _context(_any_bot(), candidates=(rated_only,)), config
        )[0]

        self.assertGreater(decision.reason["performance_score"], 0.0)
        self.assertEqual(decision.reason["availability_risk"], 0.0)

    def test_rating_form_counts_toward_form(self) -> None:
        from app.synthetic_traders.engines.stats_value import form_score

        config = parse_strategy_config(StrategyEngine.STATS_VALUE, _stats_value_payload())
        hot = PlayerStatsContext(rating_form=0.5)
        self.assertAlmostEqual(form_score(hot, config.stats_inputs) or 0.0, 1.0)
        self.assertIsNone(form_score(PlayerStatsContext(), config.stats_inputs))


def _any_bot() -> SyntheticTraderBotRecord:
    return SyntheticTraderBotRecord(
        id=uuid4(),
        account_id=uuid4(),
        portfolio_id=uuid4(),
        config_id=uuid4(),
        bot_key="stats",
        display_name="Stats",
        status=BotStatus.ACTIVE,
        config_overrides={},
        last_ticked_at=None,
        next_tick_after=None,
        created_at=AS_OF,
        updated_at=AS_OF,
    )


if __name__ == "__main__":
    unittest.main()
