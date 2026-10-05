from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

from app.clients.trading_engine import IssueInitialSupplyCommand, TradingEngineClientError
from app.seeding.portfolios import (
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
            # The reserve keeps at least its floor and absorbs whatever the bots don't take.
            self.assertGreaterEqual(reserve[0].quantity, 100)
            self.assertEqual(reserve[0].portfolio_id, RESERVE_PORTFOLIO_ID)
            bot_allocations = [item for item in allocations if not item.is_reserve]
            self.assertGreaterEqual(len(bot_allocations), 3)
            self.assertTrue(all(1 <= item.quantity <= 250 for item in bot_allocations))
            self.assertTrue(all(item.quantity == int(item.quantity) for item in bot_allocations))

        positions_by_bot = {
            bot.bot_id: sum(1 for item in first.allocations if item.bot_id == bot.bot_id)
            for bot in snapshot.bots
        }
        # Three players with a three-holder floor: nine positions spread over six bots.
        self.assertTrue(all(1 <= count <= 2 for count in positions_by_bot.values()))
        self.assertEqual(first.bot_positions, 9)
        self.assertEqual(first.reserve_positions, 3)
        self.assertEqual(first.total_bot_cash, Decimal("2100"))
        self.assertEqual(first.average_bot_cash, Decimal("350"))
        distribution = first.bot_distribution()
        self.assertEqual(distribution["min_positions_per_bot"], 1)
        self.assertEqual(distribution["max_positions_per_bot"], 2)
        self.assertEqual(distribution["avg_shares_per_bot"], round(first.bot_shares / 6, 2))

    def test_bots_get_balanced_seed_value_over_several_positions(self) -> None:
        prices = (Decimal("1"), Decimal("4"), Decimal("18"), Decimal("75"), Decimal("200"))
        instruments = tuple(
            BootstrapInstrument(
                instrument_id=UUID(int=300 + index),
                player_id=UUID(int=400 + index),
                symbol=f"P{index}",
                seed_price=prices[index % len(prices)],
                total_supply=1_000_000,
                stats_value=float(index),
                market_value=float(index * 3 % 17),
            )
            for index in range(20)
        )
        strategies = (
            StrategyEngine.STATS_VALUE,
            StrategyEngine.NOISE,
            StrategyEngine.MARKET_MOMENTUM,
            StrategyEngine.PORTFOLIO_REBALANCER,
            StrategyEngine.BETTING_MARKET_VALUE,
        )
        snapshot = BootstrapSnapshot(
            bots=tuple(_bot(index, strategies[index % 5]) for index in range(1, 41)),
            instruments=instruments,
        )
        options = BootstrapOptions(
            seed=9,
            min_holders_per_player=5,
            target_seed_value_per_bot=Decimal("50000"),
            seed_value_jitter_percent=Decimal("20"),
        )

        plan = allocate_bootstrap(snapshot, options)

        values = {bot.bot_id: Decimal("0") for bot in snapshot.bots}
        positions = {bot.bot_id: 0 for bot in snapshot.bots}
        holders: dict[UUID, int] = {}
        for item in plan.allocations:
            if item.bot_id is None:
                continue
            values[item.bot_id] += item.quantity * item.seed_price
            positions[item.bot_id] += 1
            holders[item.instrument_id] = holders.get(item.instrument_id, 0) + 1
        # Every bot lands within the jitter band, whatever the price of the players it drew.
        for value in values.values():
            self.assertGreaterEqual(value, Decimal("39500"))
            self.assertLessEqual(value, Decimal("60000"))
        self.assertTrue(all(count >= 1 for count in positions.values()))
        self.assertTrue(all(holders[item.instrument_id] >= 5 for item in instruments))
        for instrument in instruments:
            issued = sum(
                item.quantity
                for item in plan.allocations
                if item.instrument_id == instrument.instrument_id
            )
            self.assertEqual(issued, instrument.total_supply)

    def test_capped_positions_move_value_to_the_bots_other_players(self) -> None:
        # Two players: one tiny, one deep. Each bot holds both, but the tiny player can
        # only absorb a fraction of the requested value, so the rest goes to the deep one.
        tiny = BootstrapInstrument(UUID(int=501), UUID(int=601), "TINY", Decimal("1"), 1000)
        deep = BootstrapInstrument(UUID(int=502), UUID(int=602), "DEEP", Decimal("1"), 1_000_000)
        snapshot = BootstrapSnapshot(
            bots=tuple(_bot(index, StrategyEngine.NOISE) for index in range(1, 4)),
            instruments=(tiny, deep),
        )
        options = BootstrapOptions(
            seed=3,
            min_holders_per_player=3,
            max_player_supply_per_bot=Decimal("30"),
            target_seed_value_per_bot=Decimal("10000"),
            seed_value_jitter_percent=Decimal("0"),
        )

        plan = allocate_bootstrap(snapshot, options)

        tiny_items = [item for item in plan.allocations if item.instrument_id == tiny.instrument_id]
        self.assertTrue(all(item.quantity <= 300 for item in tiny_items if not item.is_reserve))
        self.assertGreaterEqual(
            next(item.quantity for item in tiny_items if item.is_reserve), 100
        )
        for bot in snapshot.bots:
            total = sum(
                item.quantity * item.seed_price
                for item in plan.allocations
                if item.bot_id == bot.bot_id
            )
            self.assertGreaterEqual(total, Decimal("9998"))
            self.assertLessEqual(total, Decimal("10000"))

    def test_more_valuable_players_get_more_holders(self) -> None:
        snapshot = _priced_market()
        options = BootstrapOptions(
            seed=11,
            min_holders_per_player=3,
            target_seed_value_per_bot=Decimal("20000"),
        )

        plan = allocate_bootstrap(snapshot, options)

        holders = _holders_by_symbol(plan, snapshot)
        # The most valuable player is held by 40% of the 40 bots.
        self.assertEqual(holders["P30"], 16)
        # Holder counts climb with price, and every player keeps the floor.
        self.assertGreater(holders["P30"], 2 * holders["P1"])
        self.assertTrue(all(count >= 3 for count in holders.values()))
        averages = [item["avg_holders"] for item in plan.holders_by_price_quintile()]
        self.assertEqual(len(averages), 5)
        self.assertEqual(averages, sorted(averages))
        self.assertGreater(averages[-1], 2 * averages[0])

    def test_zero_holder_price_exponent_spreads_holders_evenly(self) -> None:
        snapshot = _priced_market()
        options = BootstrapOptions(
            seed=11,
            min_holders_per_player=3,
            target_seed_value_per_bot=Decimal("20000"),
            holder_price_exponent=0.0,
        )

        holders = _holders_by_symbol(allocate_bootstrap(snapshot, options), snapshot)

        self.assertLessEqual(max(holders.values()) - min(holders.values()), 2)

    def test_seed_keeps_every_bot_inside_its_own_risk_limits(self) -> None:
        # Noise-trader limits: 8% of equity per player, 20% per club, 5% cash reserve.
        instruments = tuple(
            BootstrapInstrument(
                instrument_id=UUID(int=900 + rank),
                player_id=UUID(int=950 + rank),
                symbol=f"C{rank}",
                seed_price=Decimal(1 + rank * 7),
                total_supply=1_000_000,
                market_value=float(rank),
                club=f"Club {rank % 10}",
            )
            for rank in range(1, 101)
        )
        bots = tuple(
            BootstrapBot(
                bot_id=UUID(int=index),
                account_id=UUID(int=1000 + index),
                portfolio_id=UUID(int=2000 + index),
                bot_key=f"bot-{index}",
                strategy_engine=StrategyEngine.NOISE,
                cash_balance=Decimal("100000"),
                max_player_position_pct=0.08,
                max_team_exposure_pct=0.20,
                min_cash_reserve_pct=0.05,
            )
            for index in range(1, 31)
        )
        snapshot = BootstrapSnapshot(bots=bots, instruments=instruments)

        plan = allocate_bootstrap(snapshot, BootstrapOptions(seed=5, min_holders_per_player=3))

        clubs = {item.instrument_id: item.club for item in instruments}
        for bot in bots:
            held = [item for item in plan.allocations if item.bot_id == bot.bot_id]
            seed_value = sum(item.quantity * item.seed_price for item in held)
            equity = bot.cash_balance + seed_value
            self.assertGreater(seed_value, Decimal("100000"))
            for item in held:
                self.assertLessEqual(item.quantity * item.seed_price, equity * Decimal("0.08"))
            by_club: dict[str | None, Decimal] = {}
            for item in held:
                club = clubs[item.instrument_id]
                by_club[club] = by_club.get(club, Decimal("0")) + item.quantity * item.seed_price
            self.assertTrue(all(value <= equity * Decimal("0.20") for value in by_club.values()))
            self.assertGreaterEqual(bot.cash_balance, equity * Decimal("0.05"))

    def test_holder_price_exponent_is_validated(self) -> None:
        with self.assertRaisesRegex(BootstrapAllocationError, "holder price exponent"):
            BootstrapOptions(seed=1, holder_price_exponent=-0.1).validate()

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

    def test_social_sentiment_bots_are_seeded_so_they_have_positions_to_sell(self) -> None:
        snapshot = BootstrapSnapshot(
            bots=(
                _bot(1, StrategyEngine.SOCIAL_SENTIMENT),
                _bot(2, StrategyEngine.STATS_VALUE),
                _bot(3, StrategyEngine.NOISE),
            ),
            instruments=(_snapshot().instruments[0],),
        )

        plan = allocate_bootstrap(
            snapshot,
            BootstrapOptions(
                seed=1,
                min_holders_per_player=3,
                max_player_supply_per_bot=Decimal("50"),
                reserve_supply_percent=Decimal("10"),
                max_positions_per_bot=1,
            ),
        )

        social_positions = [item for item in plan.allocations if item.bot_id == UUID(int=1)]
        self.assertEqual(len(social_positions), 1)
        self.assertGreater(social_positions[0].quantity, 0)

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


class RecordingSupplyIssuer:
    def __init__(self, error: Exception | None = None) -> None:
        self.commands: list[IssueInitialSupplyCommand] = []
        self.error = error

    def issue_initial_supply(self, command: IssueInitialSupplyCommand) -> None:
        self.commands.append(command)
        if self.error is not None:
            raise self.error


class BootstrapPersistenceTests(unittest.TestCase):
    def test_persistence_issues_supply_through_engine_and_records_audit_rows(self) -> None:
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
        issuer = RecordingSupplyIssuer()
        repository = PostgresSyntheticPortfolioBootstrapRepository("postgres://test", issuer)

        with patch(
            "app.seeding.portfolios.pooled_connection",
            return_value=RecordingConnection(cursor),
        ):
            repository.persist(plan, _persist_options())

        self.assertEqual(len(issuer.commands), 1)
        command = issuer.commands[0]
        self.assertTrue(command.request_id.startswith("initial-supply:"))
        self.assertTrue(command.request_id.endswith(f":{instrument_id}"))
        self.assertEqual(
            sorted(item.quantity for item in command.allocations), ["10", "90"]
        )
        mutations = "\n".join(cursor.statements).upper()
        self.assertEqual(mutations.count("INSERT INTO SYNTHETIC_PORTFOLIO_BOOTSTRAP_ALLOCATIONS"), 2)
        # Engine-owned tables are never written or locked by the worker.
        for table in ("POSITIONS", "ORDERS", "TRADES", "CASH_LEDGER_ENTRIES", "PRICE_SNAPSHOTS"):
            self.assertNotIn(f"INSERT INTO {table}", mutations)
        self.assertNotIn("UPDATE PORTFOLIOS", mutations)
        self.assertNotIn("FOR UPDATE", mutations)

    def test_engine_market_activity_rejection_becomes_allocation_error(self) -> None:
        instrument_id = uuid4()
        plan = BootstrapAllocationPlan(
            seed=5,
            selected_bot_ids=(),
            allocations=(
                BootstrapPositionAllocation(
                    instrument_id=instrument_id,
                    portfolio_id=RESERVE_PORTFOLIO_ID,
                    bot_id=None,
                    quantity=100,
                    seed_price=Decimal("12.50"),
                    is_reserve=True,
                ),
            ),
            instruments_processed=1,
            skipped_instruments=(),
        )
        cursor = RecordingCursor()
        issuer = RecordingSupplyIssuer(
            TradingEngineClientError(409, {"code": "instrument_has_market_activity", "message": "x"})
        )
        repository = PostgresSyntheticPortfolioBootstrapRepository("postgres://test", issuer)

        with patch(
            "app.seeding.portfolios.pooled_connection",
            return_value=RecordingConnection(cursor),
        ), self.assertRaisesRegex(BootstrapAllocationError, "acquired market history"):
            repository.persist(plan, _persist_options())

        mutations = "\n".join(cursor.statements).upper()
        self.assertNotIn("INSERT INTO SYNTHETIC_PORTFOLIO_BOOTSTRAP_ALLOCATIONS", mutations)


def _persist_options() -> BootstrapOptions:
    return BootstrapOptions(
        seed=5,
        min_holders_per_player=1,
        max_player_supply_per_bot=Decimal("90"),
        reserve_supply_percent=Decimal("10"),
        max_positions_per_bot=1,
    )


def _bot(index: int, strategy: StrategyEngine) -> BootstrapBot:
    return BootstrapBot(
        bot_id=UUID(int=index),
        account_id=UUID(int=1000 + index),
        portfolio_id=UUID(int=2000 + index),
        bot_key=f"bot-{index}",
        strategy_engine=strategy,
        cash_balance=Decimal(index * 100),
    )


def _priced_market() -> BootstrapSnapshot:
    # 30 players priced 1..225 (P1 cheapest, P30 dearest) and 40 bots of mixed strategies.
    instruments = tuple(
        BootstrapInstrument(
            instrument_id=UUID(int=700 + rank),
            player_id=UUID(int=800 + rank),
            symbol=f"P{rank}",
            seed_price=Decimal(1 + (rank - 1) ** 2 // 4),
            total_supply=1_000_000,
            stats_value=float(rank % 7),
            market_value=float(rank),
        )
        for rank in range(1, 31)
    )
    strategies = (StrategyEngine.NOISE, StrategyEngine.STATS_VALUE, StrategyEngine.MARKET_MOMENTUM)
    bots = tuple(_bot(index, strategies[index % 3]) for index in range(1, 41))
    return BootstrapSnapshot(bots=bots, instruments=instruments)


def _holders_by_symbol(plan: BootstrapAllocationPlan, snapshot: BootstrapSnapshot) -> dict[str, int]:
    symbols = {item.instrument_id: item.symbol for item in snapshot.instruments}
    holders = {symbol: 0 for symbol in symbols.values()}
    for item in plan.allocations:
        if not item.is_reserve:
            holders[symbols[item.instrument_id]] += 1
    return holders


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
