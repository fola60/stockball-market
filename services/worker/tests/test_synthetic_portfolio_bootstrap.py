from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

from app.synthetic_traders.bootstrap import (
    RESERVE_PORTFOLIO_ID,
    BootstrapAllocationError,
    BootstrapAllocationPlan,
    BootstrapAlreadyExistsError,
    BootstrapBot,
    BootstrapInstrument,
    BootstrapOptions,
    BootstrapPositionAllocation,
    BootstrapSnapshot,
    PostgresSyntheticPortfolioBootstrapRepository,
    SyntheticPortfolioBootstrapService,
    _profile_weight,
    _rank_signal,
    allocate_bootstrap,
)
from app.synthetic_traders.models import StrategyEngine


class FakeBootstrapRepository:
    def __init__(self, snapshot: BootstrapSnapshot) -> None:
        self.snapshot = snapshot
        self.persisted: list[BootstrapAllocationPlan] = []

    def load_snapshot(self, *, bot_ids, all_active_synthetic_bots):
        return self.snapshot

    def persist(self, plan, options) -> None:
        self.persisted.append(plan)


class SyntheticPortfolioBootstrapTests(unittest.TestCase):
    def test_seeded_allocation_is_deterministic_and_reconciles_exact_supply(self) -> None:
        snapshot = _snapshot()
        options = BootstrapOptions(
            seed=4123,
            min_holders_per_player=3,
            max_player_supply_per_bot=Decimal("25"),
            reserve_supply_percent=Decimal("10"),
            max_positions_per_bot=2,
        )

        first = allocate_bootstrap(snapshot, options)
        second = allocate_bootstrap(snapshot, options)

        self.assertEqual(first, second)
        for instrument in snapshot.instruments:
            allocations = [
                item for item in first.allocations if item.instrument_id == instrument.instrument_id
            ]
            self.assertEqual(sum(item.quantity for item in allocations), instrument.total_supply)
            reserve = [item for item in allocations if item.is_reserve]
            self.assertEqual(len(reserve), 1)
            self.assertEqual(reserve[0].quantity, 100)
            self.assertEqual(reserve[0].portfolio_id, RESERVE_PORTFOLIO_ID)
            bot_allocations = [item for item in allocations if not item.is_reserve]
            self.assertGreaterEqual(len(bot_allocations), 4)
            self.assertTrue(all(item.quantity <= 250 for item in bot_allocations))
            self.assertTrue(all(item.quantity == int(item.quantity) for item in bot_allocations))

        positions_by_bot = {
            bot.bot_id: sum(1 for item in first.allocations if item.bot_id == bot.bot_id)
            for bot in snapshot.bots
        }
        self.assertTrue(all(count == 2 for count in positions_by_bot.values()))
        self.assertEqual(first.bot_positions, 12)
        self.assertEqual(first.reserve_positions, 3)
        self.assertEqual(first.total_bot_cash, Decimal("2100"))
        self.assertEqual(first.average_bot_cash, Decimal("350"))
        self.assertEqual(
            first.bot_distribution(),
            {
                "min_positions_per_bot": 2,
                "max_positions_per_bot": 2,
                "avg_positions_per_bot": 2.0,
                "min_shares_per_bot": min(
                    sum(item.quantity for item in first.allocations if item.bot_id == bot.bot_id)
                    for bot in snapshot.bots
                ),
                "max_shares_per_bot": max(
                    sum(item.quantity for item in first.allocations if item.bot_id == bot.bot_id)
                    for bot in snapshot.bots
                ),
                "avg_shares_per_bot": 450.0,
            },
        )

    def test_profile_weights_prefer_their_primary_available_signal(self) -> None:
        snapshot = _snapshot()
        ranks = {
            "stats": _rank_signal(snapshot.instruments, "stats_value"),
            "market": _rank_signal(snapshot.instruments, "market_value"),
            "betting": _rank_signal(snapshot.instruments, "betting_probability"),
        }
        stats_bot = _bot(90, StrategyEngine.STATS_VALUE)
        betting_bot = _bot(91, StrategyEngine.BETTING_MARKET_VALUE)
        low, middle, high = snapshot.instruments

        self.assertGreater(
            _profile_weight(stats_bot, high, ranks, 1),
            _profile_weight(stats_bot, low, ranks, 1),
        )
        self.assertGreater(
            _profile_weight(betting_bot, low, ranks, 1),
            _profile_weight(betting_bot, high, ranks, 1),
        )
        self.assertNotEqual(
            _profile_weight(stats_bot, middle, ranks, 1),
            _profile_weight(betting_bot, middle, ranks, 1),
        )

    def test_missing_signals_fall_back_to_seeded_random_allocation(self) -> None:
        instruments = tuple(
            BootstrapInstrument(
                instrument_id=UUID(int=100 + index),
                player_id=UUID(int=200 + index),
                symbol=f"MISSING-{index}",
                seed_price=Decimal("10"),
                total_supply=100,
            )
            for index in range(2)
        )
        snapshot = BootstrapSnapshot(
            bots=tuple(_bot(index, StrategyEngine.STATS_VALUE) for index in range(1, 6)),
            instruments=instruments,
        )

        plan = allocate_bootstrap(
            snapshot,
            BootstrapOptions(
                seed=77,
                min_holders_per_player=2,
                max_player_supply_per_bot=Decimal("50"),
                reserve_supply_percent=Decimal("10"),
                max_positions_per_bot=2,
            ),
        )

        self.assertEqual(plan.instruments_processed, 2)
        self.assertEqual(plan.bot_shares, 180)
        self.assertEqual(plan.reserve_shares, 20)

    def test_infeasible_position_constraint_is_rejected(self) -> None:
        with self.assertRaisesRegex(BootstrapAllocationError, "bot positions"):
            allocate_bootstrap(
                _snapshot(),
                BootstrapOptions(
                    seed=1,
                    min_holders_per_player=3,
                    max_player_supply_per_bot=Decimal("25"),
                    reserve_supply_percent=Decimal("10"),
                    max_positions_per_bot=1,
                ),
            )

    def test_social_sentiment_profile_is_not_allocated(self) -> None:
        snapshot = BootstrapSnapshot(
            bots=(
                _bot(1, StrategyEngine.SOCIAL_SENTIMENT),
                _bot(2, StrategyEngine.STATS_VALUE),
                _bot(3, StrategyEngine.NOISE),
            ),
            instruments=(_snapshot().instruments[0],),
        )
        with self.assertRaisesRegex(BootstrapAllocationError, "not eligible"):
            allocate_bootstrap(
                snapshot,
                BootstrapOptions(
                    seed=1,
                    min_holders_per_player=3,
                    max_player_supply_per_bot=Decimal("50"),
                    reserve_supply_percent=Decimal("10"),
                    max_positions_per_bot=1,
                ),
            )

    def test_dry_run_does_not_persist_positions_or_audit(self) -> None:
        repository = FakeBootstrapRepository(_snapshot())
        result = SyntheticPortfolioBootstrapService(repository).bootstrap(
            all_active_synthetic_bots=True,
            seed=44,
            min_holders_per_player=3,
            max_player_supply_per_bot=Decimal("25"),
            reserve_supply_percent=Decimal("10"),
            max_positions_per_bot=3,
            dry_run=True,
        )

        self.assertEqual(result.seed, 44)
        self.assertEqual(repository.persisted, [])

    def test_repeat_allocation_failure_is_propagated(self) -> None:
        class RepeatRepository(FakeBootstrapRepository):
            def persist(self, plan, options) -> None:
                raise BootstrapAlreadyExistsError("already allocated")

        with self.assertRaisesRegex(BootstrapAlreadyExistsError, "already allocated"):
            SyntheticPortfolioBootstrapService(RepeatRepository(_snapshot())).bootstrap(
                all_active_synthetic_bots=True,
                seed=44,
                min_holders_per_player=3,
                max_player_supply_per_bot=Decimal("25"),
                reserve_supply_percent=Decimal("10"),
                max_positions_per_bot=3,
            )


class RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.last_statement = ""

    def execute(self, query, params=None) -> None:
        self.last_statement = " ".join(str(query).split())
        self.statements.append(self.last_statement)

    def fetchone(self):
        if "RETURNING id" in self.last_statement:
            return (uuid4(),)
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self.cursor_value = cursor

    def cursor(self, cursor_factory=None):
        return self.cursor_value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def close(self) -> None:
        return None


class BootstrapPersistenceTests(unittest.TestCase):
    def test_persistence_only_creates_positions_and_bootstrap_audit_rows(self) -> None:
        instrument_id = uuid4()
        bot_id = uuid4()
        plan = BootstrapAllocationPlan(
            seed=5,
            selected_bot_ids=(bot_id,),
            allocations=(
                BootstrapPositionAllocation(
                    instrument_id=instrument_id,
                    portfolio_id=uuid4(),
                    bot_id=bot_id,
                    quantity=90,
                    seed_price=Decimal("12.50"),
                ),
                BootstrapPositionAllocation(
                    instrument_id=instrument_id,
                    portfolio_id=RESERVE_PORTFOLIO_ID,
                    bot_id=None,
                    quantity=10,
                    seed_price=Decimal("12.50"),
                    is_reserve=True,
                ),
            ),
            instruments_processed=1,
            skipped_instruments=(),
        )
        cursor = RecordingCursor()
        repository = PostgresSyntheticPortfolioBootstrapRepository("postgres://test")

        with patch(
            "app.synthetic_traders.bootstrap.pooled_connection",
            return_value=RecordingConnection(cursor),
        ):
            repository.persist(
                plan,
                BootstrapOptions(
                    seed=5,
                    min_holders_per_player=1,
                    max_player_supply_per_bot=Decimal("90"),
                    reserve_supply_percent=Decimal("10"),
                    max_positions_per_bot=1,
                ),
            )

        mutations = "\n".join(cursor.statements).upper()
        self.assertEqual(mutations.count("INSERT INTO POSITIONS"), 2)
        self.assertEqual(mutations.count("INSERT INTO SYNTHETIC_PORTFOLIO_BOOTSTRAP_ALLOCATIONS"), 2)
        self.assertNotIn("INSERT INTO ORDERS", mutations)
        self.assertNotIn("INSERT INTO TRADES", mutations)
        self.assertNotIn("CASH_LEDGER_ENTRIES", mutations)
        self.assertNotIn("UPDATE PORTFOLIOS", mutations)
        self.assertNotIn("PRICE_SNAPSHOTS", mutations)


def _bot(index: int, strategy: StrategyEngine) -> BootstrapBot:
    return BootstrapBot(
        bot_id=UUID(int=index),
        account_id=UUID(int=1000 + index),
        portfolio_id=UUID(int=2000 + index),
        bot_key=f"bot-{index}",
        strategy_engine=strategy,
        cash_balance=Decimal(index * 100),
    )


def _snapshot() -> BootstrapSnapshot:
    strategies = (
        StrategyEngine.STATS_VALUE,
        StrategyEngine.STATS_VALUE,
        StrategyEngine.BETTING_MARKET_VALUE,
        StrategyEngine.MARKET_MOMENTUM,
        StrategyEngine.NOISE,
        StrategyEngine.PORTFOLIO_REBALANCER,
    )
    bots = tuple(_bot(index, strategy) for index, strategy in enumerate(strategies, start=1))
    instruments = (
        BootstrapInstrument(
            UUID(int=101), UUID(int=201), "LOW", Decimal("10"), 1000,
            stats_value=1.0, market_value=10.0, betting_probability=0.9,
        ),
        BootstrapInstrument(
            UUID(int=102), UUID(int=202), "MID", Decimal("20"), 1000,
            stats_value=5.0, market_value=50.0, betting_probability=0.5,
        ),
        BootstrapInstrument(
            UUID(int=103), UUID(int=203), "HIGH", Decimal("30"), 1000,
            stats_value=9.0, market_value=90.0, betting_probability=0.1,
        ),
    )
    return BootstrapSnapshot(bots=bots, instruments=instruments)


if __name__ == "__main__":
    unittest.main()
