from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal
from uuid import UUID

from app.synthetic_traders.startup import (
    DEFAULT_ACTIVITY_PROFILES,
    DevMarketBootstrapError,
    DevMarketBootstrapOptions,
    DevMarketBootstrapService,
    FleetPlanningOptions,
    FleetProfileState,
    FundingResult,
    InstrumentSignal,
    PortfolioResult,
    StartupSnapshot,
    ValuationOptions,
    build_valuation_plan,
    plan_fleet,
)


class DevMarketFleetPlanningTests(unittest.TestCase):
    def test_plan_meets_floor_with_diverse_profile_mix(self) -> None:
        snapshot = _snapshot(instrument_count=20)

        plan = plan_fleet(
            snapshot,
            FleetPlanningOptions(
                target_trades_per_hour_per_instrument=2,
                max_bots=500,
                popularity_headroom=0.25,
            ),
        )

        self.assertGreaterEqual(plan.projected_trades_per_hour, 50)
        self.assertGreaterEqual(plan.projected_min_instrument_trades_per_hour, 2)
        self.assertGreater(plan.projected_max_instrument_trades_per_hour, 2)
        self.assertTrue(all(profile.target_count >= 1 for profile in plan.profiles))
        self.assertTrue(
            all(
                profile.config_overrides["universe"]["max_candidates"] >= 20
                for profile in plan.profiles
            )
        )
        noise_profiles = {
            profile.config_key: profile for profile in plan.profiles
            if profile.config_key.startswith("NOISE_")
        }
        self.assertTrue(
            all(
                profile.config_overrides["randomness"]["activity_floor_weight"] == 0.65
                for profile in noise_profiles.values()
            )
        )

    def test_plan_is_deterministic_and_reuses_existing_fleet(self) -> None:
        snapshot = _snapshot(instrument_count=8)
        options = FleetPlanningOptions(1.0, max_bots=200)
        initial = plan_fleet(snapshot, options)
        existing = replace(
            snapshot,
            profiles=tuple(
                replace(profile, existing_count=planned.target_count)
                for profile, planned in zip(snapshot.profiles, initial.profiles, strict=True)
            ),
        )

        rerun = plan_fleet(existing, options)

        self.assertEqual(rerun, plan_fleet(existing, options))
        self.assertEqual(rerun.create_count, 0)

    def test_impossible_target_reports_max_bot_limit(self) -> None:
        with self.assertRaisesRegex(DevMarketBootstrapError, "max-bots=10"):
            plan_fleet(
                _snapshot(instrument_count=100),
                FleetPlanningOptions(10, max_bots=10),
            )

    def test_unlimited_fleet_has_no_bot_cap(self) -> None:
        plan = plan_fleet(
            _snapshot(instrument_count=100),
            FleetPlanningOptions(10, max_bots=None),
        )

        self.assertGreater(plan.calculated_bot_count, 10)
        self.assertGreaterEqual(plan.projected_min_instrument_trades_per_hour, 10)


class DevMarketValuationTests(unittest.TestCase):
    def test_valuation_uses_market_stats_and_lower_weighted_social_signal(self) -> None:
        instruments = (
            _instrument(1, market=10_000_000, stats=1, social=1),
            _instrument(2, market=50_000_000, stats=5, social=-1),
            _instrument(3, market=90_000_000, stats=9, social=0),
        )

        plans = build_valuation_plan(instruments, ValuationOptions())

        self.assertEqual(len(plans), 3)
        self.assertTrue(all(plan.new_price > 0 for plan in plans))
        self.assertGreater(plans[2].new_price, plans[1].new_price)
        self.assertGreater(plans[1].new_price, plans[0].new_price)

    def test_valuation_clamps_to_configured_positive_floor(self) -> None:
        plan = build_valuation_plan(
            (_instrument(1, market=None, stats=None, social=None, position="GK"),),
            ValuationOptions(minimum_price=Decimal("10")),
        )[0]

        self.assertEqual(plan.new_price, Decimal("10"))

    def test_traded_non_positive_instrument_is_rejected(self) -> None:
        unsafe = replace(_instrument(1), current_price=Decimal("0"), has_activity=True)

        with self.assertRaisesRegex(DevMarketBootstrapError, "cannot repair"):
            build_valuation_plan((unsafe,), ValuationOptions())

    def test_existing_or_traded_instruments_are_not_revalued(self) -> None:
        instruments = (
            replace(_instrument(1), already_valued=True),
            replace(_instrument(2), has_activity=True),
            replace(_instrument(3), has_positions=True),
        )

        self.assertEqual(build_valuation_plan(instruments, ValuationOptions()), ())


class DevMarketBootstrapServiceTests(unittest.TestCase):
    def test_dry_run_is_read_only_and_reports_planned_work(self) -> None:
        repository = _FakeRepository(_snapshot(instrument_count=5))
        seeder = _MutationGuard()
        spawner = _MutationGuard()
        funder = _MutationGuard()
        portfolios = _MutationGuard()
        service = DevMarketBootstrapService(
            repository=repository,
            instrument_seeder=seeder,
            spawner=spawner,
            funder=funder,
            portfolio_bootstrapper=portfolios,
        )

        report = service.run(
            DevMarketBootstrapOptions(
                fleet=FleetPlanningOptions(1, max_bots=200),
            )
        )

        self.assertTrue(report.dry_run)
        self.assertGreater(report.fleet.create_count, 0)
        self.assertEqual(repository.applied_valuations, [])
        self.assertEqual(repository.activity_updates, [])


class _FakeRepository:
    def __init__(self, snapshot: StartupSnapshot) -> None:
        self.snapshot = snapshot
        self.applied_valuations = []
        self.activity_updates = []

    def load_snapshot(self) -> StartupSnapshot:
        return self.snapshot

    def apply_valuations(self, valuations, options) -> int:
        self.applied_valuations.extend(valuations)
        return len(valuations)

    def apply_activity_overrides(self, profiles) -> int:
        self.activity_updates.extend(profiles)
        return len(profiles)


class _MutationGuard:
    def seed(self):
        raise AssertionError("dry-run called instrument seeder")

    def spawn(self, command):
        raise AssertionError("dry-run called spawner")

    def fund(self, amount) -> FundingResult:
        raise AssertionError("dry-run called funder")

    def initialize(self, **kwargs) -> PortfolioResult:
        raise AssertionError("dry-run called portfolio bootstrapper")


def _snapshot(instrument_count: int) -> StartupSnapshot:
    instruments = tuple(_instrument(index + 1) for index in range(instrument_count))
    profiles = tuple(
        FleetProfileState(spec=spec, base_config=_base_config(), existing_count=0)
        for spec in DEFAULT_ACTIVITY_PROFILES
    )
    return StartupSnapshot(
        player_count=instrument_count,
        instruments=instruments,
        profiles=profiles,
        unfunded_bot_count=2,
    )


def _base_config() -> dict[str, object]:
    return {
        "universe": {"max_candidates": 150},
        "risk": {"max_daily_trades": 8},
        "execution": {
            "tick_cadence_minutes": 60,
            "cooldown_minutes": 60,
            "trade_probability": 0.25,
            "max_orders_per_tick": 1,
        },
    }


def _instrument(
    index: int,
    *,
    market: float | None = 50_000_000,
    stats: float | None = 5,
    social: float | None = 0,
    position: str | None = "MID",
) -> InstrumentSignal:
    return InstrumentSignal(
        instrument_id=UUID(int=index),
        symbol=f"PLAYER-{index}",
        position=position,
        current_price=Decimal("10"),
        market_value=market,
        stats_value=stats,
        social_value=social,
        recent_trade_count=index,
        has_activity=False,
        has_positions=False,
        already_valued=False,
    )


if __name__ == "__main__":
    unittest.main()
