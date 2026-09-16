from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.clients.trading_engine import OrderSide
from app.synthetic_traders import (
    BettingMarketContext,
    BettingMarketQuote,
    BotActivityContext,
    BotPortfolioContext,
    BotPositionContext,
    BotStatus,
    BotTickContext,
    CandidateInstrumentContext,
    PlayerStatsContext,
    SocialSignalContext,
    StrategyEngine,
    SyntheticTraderBotRecord,
    parse_strategy_config,
)
from app.synthetic_traders.engines import (
    BettingMarketValueStrategyEngine,
    MarketMomentumStrategyEngine,
    NoiseStrategyEngine,
    PortfolioRebalancerStrategyEngine,
    SocialSentimentStrategyEngine,
    StatsValueStrategyEngine,
)
from app.synthetic_traders.engines.base import canonical_position_codes, filter_candidates
from app.synthetic_traders.engines.noise import hourly_activity_floor_scores
from tests.test_synthetic_trader_configs import (
    _betting_market_payload,
    _market_momentum_payload,
    _portfolio_payload,
    _social_payload,
    _stats_value_payload,
)


class FixedRandom:
    def __init__(self, random_value: float, uniform_values: list[float]) -> None:
        self._random_value = random_value
        self._uniform_values = list(uniform_values)

    def random(self) -> float:
        return self._random_value

    def uniform(self, lower: float, upper: float) -> float:
        if self._uniform_values:
            return self._uniform_values.pop(0)
        return (lower + upper) / 2


class SyntheticTraderEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.as_of = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
        self.bot = SyntheticTraderBotRecord(
            id=uuid4(),
            account_id=uuid4(),
            portfolio_id=uuid4(),
            config_id=uuid4(),
            bot_key="bot-1",
            display_name="Bot One",
            status=BotStatus.ACTIVE,
            config_overrides={},
            last_ticked_at=None,
            next_tick_after=None,
            created_at=self.as_of,
            updated_at=self.as_of,
        )

    def test_noise_engine_can_emit_buy(self) -> None:
        favorite_player_id = uuid4()
        config = parse_strategy_config(
            StrategyEngine.NOISE,
            {
                "universe": {
                    "max_candidates": 50,
                    "included_positions": ["MID"],
                    "excluded_positions": [],
                    "included_clubs": [],
                    "excluded_clubs": [],
                    "favorite_clubs": ["Arsenal"],
                    "favorite_player_ids": [str(favorite_player_id)],
                    "min_current_price": "0.0000",
                    "max_current_price": None,
                    "require_active_instrument": True,
                },
                "randomness": {
                    "random_alpha_min": -0.4,
                    "random_alpha_max": 0.4,
                    "buy_bias": 0.2,
                    "sell_bias": 0.0,
                    "favorite_club_bias": 0.12,
                    "recognizable_player_bias": 0.15,
                    "recent_mover_bias": 0.08,
                    "holding_bias": 0.05,
                },
                "signal_weights": {
                    "random_component": 0.55,
                    "popularity_bias": 0.15,
                    "recent_mover_bias": 0.1,
                    "favorite_bias": 0.1,
                    "holding_bias": 0.05,
                    "cash_pressure": 0.05,
                    "volatility_risk": -0.05,
                },
                "decision": {
                    "buy_threshold": 0.25,
                    "sell_threshold": -0.3,
                    "min_confidence": 0.2,
                    "hold_band": 0.15,
                    "allow_sells": True,
                    "sell_only_if_position_exists": True,
                },
                "risk": {
                    "max_trade_cash_pct": 0.015,
                    "min_trade_cash_amount": "10.0000",
                    "max_trade_cash_amount": "500.0000",
                    "max_player_position_pct": 0.08,
                    "max_team_exposure_pct": 0.2,
                    "min_cash_reserve_pct": 0.05,
                    "max_daily_trades": 8,
                    "max_daily_turnover_pct": 0.15,
                    "volatility_tolerance": 0.8,
                },
                "sizing": {
                    "base_cash_pct": 0.008,
                    "confidence_multiplier": 0.5,
                    "random_size_multiplier_min": 0.5,
                    "random_size_multiplier_max": 1.5,
                    "position_concentration_penalty": 0.7,
                },
                "execution": {
                    "tick_cadence_minutes": 60,
                    "cooldown_minutes": 120,
                    "decision_jitter_minutes": 30,
                    "trade_probability": 1.0,
                    "size_noise_pct": 0.0,
                    "max_orders_per_tick": 1,
                },
            },
        )
        candidate = _candidate(
            player_id=favorite_player_id,
            club="Arsenal",
            position="MID",
            recent_price_values=(Decimal("10"), Decimal("10.8"), Decimal("11.4")),
            recent_trade_sides=(OrderSide.BUY, OrderSide.BUY, OrderSide.BUY),
        )
        context = _context(self.bot, candidates=(candidate,))

        decisions = NoiseStrategyEngine(
            random_source=FixedRandom(0.0, [0.4, 1.0])
        ).evaluate(context, config)

        self.assertEqual(decisions[0].side.value, "BUY")

    def test_noise_activity_floor_prioritizes_hourly_undertraded_instruments(self) -> None:
        quiet = _candidate(recent_trade_sides=())
        active = _candidate(recent_trade_sides=(OrderSide.BUY,))

        scores = hourly_activity_floor_scores(
            (quiet, active),
            self.as_of,
            60,
        )

        self.assertEqual(scores[quiet.instrument_id], 1.0)
        self.assertEqual(scores[active.instrument_id], 0.0)

    def test_candidate_filter_normalizes_provider_position_codes(self) -> None:
        config = parse_strategy_config(StrategyEngine.STATS_VALUE, _stats_value_payload())
        candidates = (
            _candidate(position="FW"),
            _candidate(position="MF,FW"),
            _candidate(position="DF"),
            _candidate(position="GK"),
        )

        filtered = filter_candidates(candidates, config.universe)

        self.assertEqual(len(filtered), 4)
        self.assertEqual(canonical_position_codes("MF,FW"), ("MID", "FWD"))

    def test_market_momentum_engine_buys_confirmed_trend(self) -> None:
        config = parse_strategy_config(StrategyEngine.MARKET_MOMENTUM, _market_momentum_payload())
        candidate = _candidate(
            recent_price_values=(Decimal("10"), Decimal("10.7"), Decimal("11.3"), Decimal("12.0")),
            recent_trade_sides=(OrderSide.BUY, OrderSide.BUY, OrderSide.BUY, OrderSide.BUY),
            trade_amounts=(Decimal("300"), Decimal("450"), Decimal("500"), Decimal("600")),
        )
        context = _context(self.bot, candidates=(candidate,))

        decisions = MarketMomentumStrategyEngine().evaluate(context, config)

        self.assertEqual(decisions[0].side.value, "BUY")

    def test_stats_value_engine_buys_undervalued_candidate(self) -> None:
        config = parse_strategy_config(StrategyEngine.STATS_VALUE, _stats_value_payload())
        strong_candidate = _candidate(
            current_price=Decimal("15"),
            market_value=Decimal("85000000"),
            stats=PlayerStatsContext(
                observation_count=5,
                average_rating=7.8,
                average_minutes=88.0,
                goals_per_match=0.8,
                assists_per_match=0.4,
                shots_per_match=3.5,
                key_passes_per_match=2.2,
                latest_observed_at=self.as_of,
            ),
        )
        weak_candidate = _candidate(
            current_price=Decimal("45"),
            market_value=Decimal("10000000"),
            stats=PlayerStatsContext(
                observation_count=5,
                average_rating=6.2,
                average_minutes=42.0,
                goals_per_match=0.0,
                assists_per_match=0.1,
                latest_observed_at=self.as_of,
            ),
        )
        context = _context(self.bot, candidates=(strong_candidate, weak_candidate))

        decisions = StatsValueStrategyEngine().evaluate(context, config)
        decisions_by_id = {decision.instrument_id: decision for decision in decisions}

        self.assertEqual(decisions_by_id[strong_candidate.instrument_id].side.value, "BUY")

    def test_social_sentiment_engine_holds_without_signals(self) -> None:
        config = parse_strategy_config(StrategyEngine.SOCIAL_SENTIMENT, _social_payload())
        candidate = _candidate(
            social=SocialSignalContext(),
            recent_price_values=(Decimal("20"), Decimal("20.2")),
            recent_trade_sides=(OrderSide.BUY,),
        )
        context = _context(self.bot, candidates=(candidate,))

        decisions = SocialSentimentStrategyEngine().evaluate(context, config)

        self.assertEqual(decisions[0].side.value, "HOLD")

    def test_betting_market_engine_applies_limit_after_selecting_odds_players(
        self,
    ) -> None:
        payload = _betting_market_payload()
        payload["universe"]["max_candidates"] = 1
        config = parse_strategy_config(StrategyEngine.BETTING_MARKET_VALUE, payload)
        no_odds = _candidate(holding_quantity=Decimal("20"))
        with_odds = _candidate(
            betting=_betting_context(
                self.as_of,
                current_probabilities=(Decimal("0.65"), Decimal("0.72")),
                previous_probabilities=(Decimal("0.50"), Decimal("0.55")),
            )
        )

        decisions = BettingMarketValueStrategyEngine().evaluate(
            _context(self.bot, candidates=(no_odds, with_odds)),
            config,
        )

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].instrument_id, with_odds.instrument_id)

    def test_portfolio_rebalancer_engine_sells_overweight_position(self) -> None:
        config = parse_strategy_config(StrategyEngine.PORTFOLIO_REBALANCER, _portfolio_payload())
        candidate = _candidate(
            current_price=Decimal("50"),
            holding_quantity=Decimal("20"),
            recent_price_values=(Decimal("40"), Decimal("50")),
            recent_trade_sides=(OrderSide.BUY, OrderSide.BUY),
        )
        position = BotPositionContext(
            instrument_id=candidate.instrument_id,
            player_id=candidate.player_id,
            club=candidate.club,
            quantity=Decimal("20"),
            current_price=Decimal("50"),
            market_value=Decimal("1000"),
            last_trade_price=Decimal("40"),
            unrealized_return_pct=0.25,
        )
        portfolio = BotPortfolioContext(
            account_id=self.bot.account_id,
            portfolio_id=self.bot.portfolio_id,
            cash_balance=Decimal("50"),
            total_position_value=Decimal("1000"),
            total_equity=Decimal("1050"),
            positions=(position,),
        )
        context = BotTickContext(
            bot=self.bot,
            portfolio=portfolio,
            activity=BotActivityContext(
                daily_trade_count=0,
                daily_turnover_cash=Decimal("0"),
                last_order_at=None,
            ),
            candidates=(candidate,),
            as_of=self.as_of,
        )

        decisions = PortfolioRebalancerStrategyEngine().evaluate(context, config)
        decisions_by_id = {decision.instrument_id: decision for decision in decisions}

        self.assertEqual(decisions_by_id[candidate.instrument_id].side.value, "SELL")

    def test_betting_market_engine_buys_strong_probability_candidate(self) -> None:
        config = parse_strategy_config(
            StrategyEngine.BETTING_MARKET_VALUE,
            _betting_market_payload(),
        )
        strong = _candidate(
            betting=_betting_context(
                self.as_of,
                current_probabilities=(Decimal("0.65"), Decimal("0.72")),
                previous_probabilities=(Decimal("0.50"), Decimal("0.55")),
            )
        )
        weak = _candidate(
            betting=_betting_context(
                self.as_of,
                current_probabilities=(Decimal("0.15"), Decimal("0.20")),
                previous_probabilities=(Decimal("0.20"), Decimal("0.25")),
            )
        )

        decisions = BettingMarketValueStrategyEngine().evaluate(
            _context(self.bot, candidates=(strong, weak)),
            config,
        )
        decisions_by_id = {decision.instrument_id: decision for decision in decisions}

        self.assertEqual(decisions_by_id[strong.instrument_id].side.value, "BUY")

    def test_betting_market_engine_sells_weak_held_candidate(self) -> None:
        config = parse_strategy_config(
            StrategyEngine.BETTING_MARKET_VALUE,
            _betting_market_payload(),
        )
        strong = _candidate(
            betting=_betting_context(
                self.as_of,
                current_probabilities=(Decimal("0.65"), Decimal("0.72")),
                previous_probabilities=(Decimal("0.55"), Decimal("0.60")),
            )
        )
        weak = _candidate(
            holding_quantity=Decimal("5"),
            betting=_betting_context(
                self.as_of,
                current_probabilities=(Decimal("0.12"), Decimal("0.16")),
                previous_probabilities=(Decimal("0.24"), Decimal("0.28")),
            ),
        )

        decisions = BettingMarketValueStrategyEngine().evaluate(
            _context(self.bot, candidates=(strong, weak)),
            config,
        )
        decisions_by_id = {decision.instrument_id: decision for decision in decisions}

        self.assertEqual(decisions_by_id[weak.instrument_id].side.value, "SELL")

    def test_betting_market_engine_holds_stale_quotes(self) -> None:
        config = parse_strategy_config(
            StrategyEngine.BETTING_MARKET_VALUE,
            _betting_market_payload(),
        )
        stale = _candidate(
            betting=_betting_context(
                self.as_of - timedelta(hours=2),
                current_probabilities=(Decimal("0.65"), Decimal("0.72")),
                previous_probabilities=(Decimal("0.50"), Decimal("0.55")),
            )
        )

        decisions = BettingMarketValueStrategyEngine().evaluate(
            _context(self.bot, candidates=(stale,)),
            config,
        )

        self.assertEqual(decisions[0].side.value, "HOLD")


def _context(
    bot: SyntheticTraderBotRecord,
    *,
    candidates: tuple[CandidateInstrumentContext, ...],
) -> BotTickContext:
    portfolio = BotPortfolioContext(
        account_id=bot.account_id,
        portfolio_id=bot.portfolio_id,
        cash_balance=Decimal("1000"),
        total_position_value=Decimal("0"),
        total_equity=Decimal("1000"),
        positions=(),
    )
    return BotTickContext(
        bot=bot,
        portfolio=portfolio,
        activity=BotActivityContext(
            daily_trade_count=0,
            daily_turnover_cash=Decimal("0"),
            last_order_at=None,
        ),
        candidates=candidates,
        as_of=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
    )


def _candidate(
    *,
    player_id=None,
    club: str | None = "Arsenal",
    position: str | None = "MID",
    current_price: Decimal = Decimal("20"),
    recent_price_values: tuple[Decimal, ...] = (Decimal("20"), Decimal("20.5"), Decimal("21")),
    recent_trade_sides: tuple[OrderSide, ...] = (OrderSide.BUY, OrderSide.SELL),
    trade_amounts: tuple[Decimal, ...] | None = None,
    market_value: Decimal | None = Decimal("50000000"),
    stats: PlayerStatsContext | None = None,
    social: SocialSignalContext | None = None,
    betting: BettingMarketContext | None = None,
    holding_quantity: Decimal = Decimal("0"),
) -> CandidateInstrumentContext:
    candidate_player_id = player_id or uuid4()
    instrument_id = uuid4()
    if trade_amounts is None:
        trade_amounts = tuple(Decimal("300") for _ in recent_trade_sides)
    now = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
    recent_prices = tuple(
        _price_point(now - timedelta(hours=len(recent_price_values) - index), price)
        for index, price in enumerate(recent_price_values)
    )
    recent_trades = tuple(
        _trade_sample(
            instrument_id=instrument_id,
            side=side,
            gross_amount=trade_amounts[index],
            executed_at=now - timedelta(hours=len(recent_trade_sides) - index),
        )
        for index, side in enumerate(recent_trade_sides)
    )
    return CandidateInstrumentContext(
        instrument_id=instrument_id,
        player_id=candidate_player_id,
        symbol=f"SYM-{instrument_id.hex[:6]}",
        display_name="Player Share",
        club=club,
        position=position,
        current_price=current_price,
        trading_status="ACTIVE",
        current_holding_quantity=holding_quantity,
        current_holding_value=current_price * holding_quantity,
        market_value_observation=market_value,
        market_value_observed_at=now,
        recent_prices=recent_prices,
        recent_trades=recent_trades,
        stats=stats or PlayerStatsContext(observation_count=1, average_rating=7.0, average_minutes=80.0),
        social=social or SocialSignalContext(),
        betting=betting or BettingMarketContext(),
    )


def _betting_context(
    observed_at: datetime,
    *,
    current_probabilities: tuple[Decimal, Decimal],
    previous_probabilities: tuple[Decimal, Decimal],
) -> BettingMarketContext:
    market_types = ("GOALSCORER", "SCORE_OR_ASSIST")
    quotes: list[BettingMarketQuote] = []
    for market_type, previous, current in zip(
        market_types,
        previous_probabilities,
        current_probabilities,
        strict=True,
    ):
        selection_key = f"{market_type}|FULL_MATCH|ANYTIME|1|player"
        for timestamp, probability in (
            (observed_at - timedelta(minutes=10), previous),
            (observed_at, current),
        ):
            quotes.append(
                BettingMarketQuote(
                    provider_event_id="event-1",
                    canonical_selection_key=selection_key,
                    market_type=market_type,
                    outcome_type="ANYTIME",
                    line=Decimal("1"),
                    decimal_odds=Decimal("1") / probability,
                    implied_probability=probability,
                    observed_at=timestamp,
                    kickoff_at=observed_at - timedelta(minutes=30),
                )
            )
    return BettingMarketContext(quotes=tuple(quotes))


def _price_point(captured_at: datetime, price: Decimal):
    from app.synthetic_traders.models import PricePoint

    return PricePoint(price=price, captured_at=captured_at)


def _trade_sample(*, instrument_id, side, gross_amount, executed_at):
    from app.synthetic_traders.models import MarketTradeSample

    return MarketTradeSample(
        instrument_id=instrument_id,
        side=side,
        quantity=Decimal("10"),
        gross_amount=gross_amount,
        account_id=uuid4(),
        executed_at=executed_at,
    )


if __name__ == "__main__":
    unittest.main()
