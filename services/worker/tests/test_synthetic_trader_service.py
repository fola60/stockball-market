from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.clients.trading_engine import ExecuteOrderCommand, OrderExecutionRecord, OrderSide
from app.synthetic_traders import (
    BotActivityContext,
    BotPortfolioContext,
    BotStatus,
    BotTickContext,
    CandidateInstrumentContext,
    DecisionSide,
    PlayerStatsContext,
    SocialSignalContext,
    StrategyDecision,
    StrategyEngine,
    SyntheticTraderBotConfigRecord,
    SyntheticTraderBotRecord,
    SyntheticTraderService,
)
from app.synthetic_traders.models import PricePoint


class StubEngine:
    def __init__(self, decisions: tuple[StrategyDecision, ...]) -> None:
        self.decisions = decisions
        self.calls: list[BotTickContext] = []

    def evaluate(self, context: BotTickContext, config) -> tuple[StrategyDecision, ...]:
        self.calls.append(context)
        return self.decisions


class FakeTradingEngineClient:
    def __init__(self) -> None:
        self.commands: list[ExecuteOrderCommand] = []

    def execute_order(self, command: ExecuteOrderCommand) -> OrderExecutionRecord:
        self.commands.append(command)
        return OrderExecutionRecord(
            request_id=command.request_id,
            order_id=uuid4(),
            trade_id=uuid4(),
            account_id=command.account_id,
            portfolio_id=command.portfolio_id,
            instrument_id=command.instrument_id,
            side=command.side,
            quantity=command.quantity,
            execution_price="20.0000",
            gross_amount="100.0000",
            cash_balance_after="900.0000",
            position_quantity_after="5.000000",
            old_price="20.0000",
            new_price="20.0500",
            executed_at=datetime(2026, 5, 22, 12, 0, tzinfo=UTC),
        )


class FakeSyntheticTraderRepository:
    def __init__(
        self,
        *,
        bot: SyntheticTraderBotRecord,
        config: SyntheticTraderBotConfigRecord,
        portfolio: BotPortfolioContext,
        activity: BotActivityContext,
        candidates: tuple[CandidateInstrumentContext, ...],
    ) -> None:
        self.bot = bot
        self.config = config
        self.portfolio = portfolio
        self.activity = activity
        self.candidates = candidates
        self.calls: list[str] = []
        self.tick_updates: list[tuple[datetime, datetime]] = []

    def list_due_bots(self, as_of: datetime, *, limit: int = 100):
        self.calls.append("list_due_bots")
        return [self.bot]

    def get_bot_config(self, config_id):
        self.calls.append("get_bot_config")
        return self.config

    def load_portfolio_context(self, bot):
        self.calls.append("load_portfolio_context")
        return self.portfolio

    def load_activity_context(self, bot, as_of: datetime):
        self.calls.append("load_activity_context")
        return self.activity

    def load_candidate_instruments(self, portfolio, as_of: datetime):
        self.calls.append("load_candidate_instruments")
        return self.candidates

    def update_tick_state(self, bot_id, *, last_ticked_at: datetime, next_tick_after: datetime):
        self.calls.append("update_tick_state")
        self.tick_updates.append((last_ticked_at, next_tick_after))


class SyntheticTraderServiceTests(unittest.TestCase):
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
        self.candidate = CandidateInstrumentContext(
            instrument_id=uuid4(),
            player_id=uuid4(),
            symbol="PLAYER-1",
            display_name="Player One",
            club="Arsenal",
            position="MID",
            current_price=Decimal("20"),
            trading_status="ACTIVE",
            current_holding_quantity=Decimal("0"),
            current_holding_value=Decimal("0"),
            market_value_observation=Decimal("50000000"),
            market_value_observed_at=self.as_of,
            recent_prices=(
                PricePoint(price=Decimal("19"), captured_at=self.as_of),
                PricePoint(price=Decimal("20"), captured_at=self.as_of),
            ),
            recent_trades=(),
            stats=PlayerStatsContext(observation_count=1, average_rating=7.0, average_minutes=80.0),
            social=SocialSignalContext(),
        )
        self.config = SyntheticTraderBotConfigRecord(
            id=self.bot.config_id,
            config_key="NOISE_RETAIL_BUYER",
            display_name="Noise Retail Buyer",
            strategy_engine=StrategyEngine.NOISE,
            version=1,
            config=_noise_payload(),
            enabled=True,
            created_at=self.as_of,
            updated_at=self.as_of,
        )

    def test_tick_due_bots_submits_orders_through_trading_engine_and_updates_ticks(self) -> None:
        repository = FakeSyntheticTraderRepository(
            bot=self.bot,
            config=self.config,
            portfolio=BotPortfolioContext(
                account_id=self.bot.account_id,
                portfolio_id=self.bot.portfolio_id,
                cash_balance=Decimal("1000"),
                total_position_value=Decimal("0"),
                total_equity=Decimal("1000"),
                positions=(),
            ),
            activity=BotActivityContext(
                daily_trade_count=0,
                daily_turnover_cash=Decimal("0"),
                last_order_at=None,
            ),
            candidates=(self.candidate,),
        )
        client = FakeTradingEngineClient()
        engine = StubEngine(
            (
                StrategyDecision(
                    instrument_id=self.candidate.instrument_id,
                    side=DecisionSide.BUY,
                    alpha_score=0.9,
                    expected_return=0.2,
                    confidence=0.9,
                    suggested_cash_pct=0.1,
                    reason={"source": "test"},
                ),
            )
        )
        service = SyntheticTraderService(
            repository=repository,
            trading_engine_client=client,
            engine_registry={StrategyEngine.NOISE: engine},
        )

        result = service.tick_due_bots(self.as_of)

        self.assertEqual(result.submitted_count, 1)
        self.assertEqual(len(client.commands), 1)
        self.assertEqual(client.commands[0].side, OrderSide.BUY)
        self.assertTrue(client.commands[0].request_id.startswith("synthetic-trader:"))
        self.assertEqual(repository.tick_updates[0][0], self.as_of)
        self.assertGreater(repository.tick_updates[0][1], self.as_of)

    def test_risk_layer_rejects_orders_that_fail_cash_and_position_checks(self) -> None:
        repository = FakeSyntheticTraderRepository(
            bot=self.bot,
            config=self.config,
            portfolio=BotPortfolioContext(
                account_id=self.bot.account_id,
                portfolio_id=self.bot.portfolio_id,
                cash_balance=Decimal("5"),
                total_position_value=Decimal("0"),
                total_equity=Decimal("5"),
                positions=(),
            ),
            activity=BotActivityContext(
                daily_trade_count=0,
                daily_turnover_cash=Decimal("0"),
                last_order_at=None,
            ),
            candidates=(self.candidate,),
        )
        client = FakeTradingEngineClient()
        engine = StubEngine(
            (
                StrategyDecision(
                    instrument_id=self.candidate.instrument_id,
                    side=DecisionSide.BUY,
                    alpha_score=0.8,
                    expected_return=0.1,
                    confidence=0.8,
                    suggested_cash_pct=0.5,
                    reason={"source": "test"},
                ),
                StrategyDecision(
                    instrument_id=self.candidate.instrument_id,
                    side=DecisionSide.SELL,
                    alpha_score=-0.8,
                    expected_return=-0.1,
                    confidence=0.8,
                    suggested_cash_pct=0.5,
                    reason={"source": "test"},
                ),
            )
        )
        service = SyntheticTraderService(
            repository=repository,
            trading_engine_client=client,
            engine_registry={StrategyEngine.NOISE: engine},
        )

        result = service.tick_due_bots(self.as_of)

        self.assertEqual(result.submitted_count, 0)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(client.commands, [])

    def test_service_only_mutates_tick_state_locally_and_uses_trading_engine_for_orders(self) -> None:
        repository = FakeSyntheticTraderRepository(
            bot=self.bot,
            config=self.config,
            portfolio=BotPortfolioContext(
                account_id=self.bot.account_id,
                portfolio_id=self.bot.portfolio_id,
                cash_balance=Decimal("1000"),
                total_position_value=Decimal("0"),
                total_equity=Decimal("1000"),
                positions=(),
            ),
            activity=BotActivityContext(
                daily_trade_count=0,
                daily_turnover_cash=Decimal("0"),
                last_order_at=None,
            ),
            candidates=(self.candidate,),
        )
        client = FakeTradingEngineClient()
        engine = StubEngine(
            (
                StrategyDecision(
                    instrument_id=self.candidate.instrument_id,
                    side=DecisionSide.BUY,
                    alpha_score=0.9,
                    expected_return=0.2,
                    confidence=0.9,
                    suggested_cash_pct=0.1,
                    reason={"source": "test"},
                ),
            )
        )
        service = SyntheticTraderService(
            repository=repository,
            trading_engine_client=client,
            engine_registry={StrategyEngine.NOISE: engine},
        )

        service.tick_due_bots(self.as_of)

        self.assertEqual(repository.calls.count("update_tick_state"), 1)
        self.assertEqual(client.commands[0].instrument_id, self.candidate.instrument_id)
        self.assertNotIn("update_trades", repository.calls)
        self.assertNotIn("update_positions", repository.calls)


def _noise_payload() -> dict[str, object]:
    return {
        "universe": {
            "max_candidates": 150,
            "included_positions": ["FWD", "MID", "DEF", "GK"],
            "excluded_positions": [],
            "included_clubs": [],
            "excluded_clubs": [],
            "favorite_clubs": [],
            "favorite_player_ids": [],
            "min_current_price": "0.0000",
            "max_current_price": None,
            "require_active_instrument": True,
        },
        "randomness": {
            "random_alpha_min": -0.4,
            "random_alpha_max": 0.4,
            "buy_bias": 0.08,
            "sell_bias": 0.0,
            "favorite_club_bias": 0.12,
            "recognizable_player_bias": 0.1,
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
            "max_trade_cash_pct": 0.2,
            "min_trade_cash_amount": "10.0000",
            "max_trade_cash_amount": "500.0000",
            "max_player_position_pct": 0.3,
            "max_team_exposure_pct": 0.5,
            "min_cash_reserve_pct": 0.0,
            "max_daily_trades": 8,
            "max_daily_turnover_pct": 0.5,
            "volatility_tolerance": 0.8,
        },
        "sizing": {
            "base_cash_pct": 0.05,
            "confidence_multiplier": 0.5,
            "random_size_multiplier_min": 1.0,
            "random_size_multiplier_max": 1.0,
            "position_concentration_penalty": 0.0,
        },
        "execution": {
            "tick_cadence_minutes": 60,
            "cooldown_minutes": 0,
            "decision_jitter_minutes": 10,
            "trade_probability": 1.0,
            "size_noise_pct": 0.0,
            "max_orders_per_tick": 1,
        },
    }


if __name__ == "__main__":
    unittest.main()
