from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from app.clients import (
    AccountRecord,
    CreateSyntheticTraderAccountCommand,
    PortfolioRecord,
)
from app.synthetic_traders import (
    BotStatus,
    CreateSyntheticTraderBotCommand,
    SpawnNameStyle,
    SpawnSyntheticTraderCommand,
    StrategyEngine,
    SyntheticTraderBotConfigRecord,
    SyntheticTraderBotRecord,
    SyntheticTraderConfigNotFoundError,
    SyntheticTraderSpawner,
)


class FakeApiClient:
    def __init__(self) -> None:
        self.commands: list[CreateSyntheticTraderAccountCommand] = []

    def create_synthetic_trader_account(
        self,
        command: CreateSyntheticTraderAccountCommand,
    ) -> AccountRecord:
        self.commands.append(command)
        account_id = uuid4()
        return AccountRecord(
            id=account_id,
            handle=command.handle,
            email=command.email,
            display_name=command.display_name,
            account_type="SYNTHETIC_TRADER",
            status="ACTIVE",
            created_at=_timestamp(),
            updated_at=_timestamp(),
            portfolio=PortfolioRecord(
                id=uuid4(),
                account_id=account_id,
                cash_balance="0.0000",
                created_at=_timestamp(),
                updated_at=_timestamp(),
            ),
        )


class FakeSyntheticTraderRepository:
    def __init__(self, config: SyntheticTraderBotConfigRecord | None) -> None:
        self.config = config
        self.created_bots: list[CreateSyntheticTraderBotCommand] = []
        self.lookup_keys: list[str] = []

    def get_bot_config_by_key(self, config_key: str):
        self.lookup_keys.append(config_key)
        if self.config is None or self.config.config_key != config_key:
            return None
        return self.config

    def create_bot(self, command: CreateSyntheticTraderBotCommand) -> SyntheticTraderBotRecord:
        self.created_bots.append(command)
        return SyntheticTraderBotRecord(
            id=uuid4(),
            account_id=command.account_id,
            portfolio_id=uuid4(),
            config_id=command.config_id,
            bot_key=command.bot_key,
            display_name=command.display_name,
            status=command.status,
            config_overrides=command.config_overrides or {},
            last_ticked_at=None,
            next_tick_after=None,
            created_at=_timestamp(),
            updated_at=_timestamp(),
        )


class SyntheticTraderSpawnerTests(unittest.TestCase):
    def test_spawn_creates_accounts_through_api_and_attaches_bots(self) -> None:
        config_id = uuid4()
        repository = FakeSyntheticTraderRepository(_config(config_id))
        api_client = FakeApiClient()
        spawner = SyntheticTraderSpawner(
            api_client=api_client,
            repository=repository,
        )

        result = spawner.spawn(
            SpawnSyntheticTraderCommand(
                config_key="NOISE_RETAIL_BUYER",
                count=2,
                handle_prefix="noise-buyer",
                display_name_prefix="Noise Buyer",
                name_style=SpawnNameStyle.NUMBERED,
                start_index=3,
                status=BotStatus.PAUSED,
            )
        )

        self.assertEqual(result.spawned_count, 2)
        self.assertEqual([command.handle for command in api_client.commands], ["noise-buyer-003", "noise-buyer-004"])
        self.assertEqual([command.bot_key for command in repository.created_bots], ["noise-buyer-003", "noise-buyer-004"])
        self.assertEqual(repository.created_bots[0].config_id, config_id)
        self.assertEqual(repository.created_bots[0].status, BotStatus.PAUSED)

    def test_spawn_randomizes_config_overrides_with_reproducible_seed(self) -> None:
        first_repository = FakeSyntheticTraderRepository(
            _config(
                uuid4(),
                config_key="STATS_VALUE_CONSERVATIVE",
                strategy_engine=StrategyEngine.STATS_VALUE,
                config=_stats_value_randomization_config(),
            )
        )
        second_repository = FakeSyntheticTraderRepository(
            _config(
                uuid4(),
                config_key="STATS_VALUE_CONSERVATIVE",
                strategy_engine=StrategyEngine.STATS_VALUE,
                config=_stats_value_randomization_config(),
            )
        )

        for repository in (first_repository, second_repository):
            SyntheticTraderSpawner(
                api_client=FakeApiClient(),
                repository=repository,
            ).spawn(
                SpawnSyntheticTraderCommand(
                    config_key="STATS_VALUE_CONSERVATIVE",
                    count=2,
                    handle_prefix="stats-value",
                    display_name_prefix="Stats Value",
                    name_style=SpawnNameStyle.NUMBERED,
                    random_seed=123,
                )
            )

        first_overrides = [
            command.config_overrides for command in first_repository.created_bots
        ]
        second_overrides = [
            command.config_overrides for command in second_repository.created_bots
        ]

        self.assertEqual(first_overrides, second_overrides)
        self.assertNotEqual(first_overrides[0], first_overrides[1])
        stats_form = first_overrides[0]["signal_weights"]["stats_form"]
        self.assertGreaterEqual(stats_form, 0.255)
        self.assertLessEqual(stats_form, 0.345)
        fair_value_blend = first_overrides[0]["valuation"]["fair_value_blend"]
        self.assertAlmostEqual(sum(fair_value_blend.values()), 1.0, places=5)

    def test_spawn_resolves_strategy_engine_to_default_config_key(self) -> None:
        config_id = uuid4()
        repository = FakeSyntheticTraderRepository(
            _config(
                config_id,
                config_key="STATS_VALUE_CONSERVATIVE",
                strategy_engine=StrategyEngine.STATS_VALUE,
            )
        )
        api_client = FakeApiClient()
        spawner = SyntheticTraderSpawner(
            api_client=api_client,
            repository=repository,
        )

        result = spawner.spawn(
            SpawnSyntheticTraderCommand(
                strategy_engine=StrategyEngine.STATS_VALUE,
                count=1,
                handle_prefix="stats-value",
                display_name_prefix="Stats Value",
            )
        )

        self.assertEqual(repository.lookup_keys, ["STATS_VALUE_CONSERVATIVE"])
        self.assertEqual(result.config_key, "STATS_VALUE_CONSERVATIVE")
        self.assertEqual(result.spawned_count, 1)
        self.assertEqual(repository.created_bots[0].config_id, config_id)

    def test_spawn_resolves_betting_engine_to_conservative_profile(self) -> None:
        config_id = uuid4()
        repository = FakeSyntheticTraderRepository(
            _config(
                config_id,
                config_key="BETTING_MARKET_CONSERVATIVE",
                strategy_engine=StrategyEngine.BETTING_MARKET_VALUE,
            )
        )

        result = SyntheticTraderSpawner(
            api_client=FakeApiClient(),
            repository=repository,
        ).spawn(
            SpawnSyntheticTraderCommand(
                strategy_engine=StrategyEngine.BETTING_MARKET_VALUE,
                count=1,
                random_seed=42,
            )
        )

        self.assertEqual(repository.lookup_keys, ["BETTING_MARKET_CONSERVATIVE"])
        self.assertEqual(result.config_key, "BETTING_MARKET_CONSERVATIVE")

    def test_spawn_uses_seeded_persona_names_by_default(self) -> None:
        first_repository = FakeSyntheticTraderRepository(_config(uuid4()))
        second_repository = FakeSyntheticTraderRepository(_config(uuid4()))

        for repository in (first_repository, second_repository):
            SyntheticTraderSpawner(
                api_client=FakeApiClient(),
                repository=repository,
            ).spawn(
                SpawnSyntheticTraderCommand(
                    config_key="NOISE_RETAIL_BUYER",
                    count=3,
                    random_seed=987,
                )
            )

        first_names = [
            (command.bot_key, command.display_name)
            for command in first_repository.created_bots
        ]
        second_names = [
            (command.bot_key, command.display_name)
            for command in second_repository.created_bots
        ]

        self.assertEqual(first_names, second_names)
        self.assertEqual(len({handle for handle, _ in first_names}), 3)
        self.assertNotIn("noise", first_names[0][0])
        self.assertNotIn("buyer", first_names[0][0])
        self.assertIn(" ", first_names[0][1])

    def test_spawn_raises_when_config_key_is_missing(self) -> None:
        spawner = SyntheticTraderSpawner(
            api_client=FakeApiClient(),
            repository=FakeSyntheticTraderRepository(None),
        )

        with self.assertRaises(SyntheticTraderConfigNotFoundError):
            spawner.spawn(
                SpawnSyntheticTraderCommand(
                    config_key="MISSING",
                    count=1,
                    handle_prefix="missing",
                    display_name_prefix="Missing",
                )
            )


def _config(
    config_id,
    config_key: str = "NOISE_RETAIL_BUYER",
    strategy_engine: StrategyEngine = StrategyEngine.NOISE,
    config: dict | None = None,
):
    return SyntheticTraderBotConfigRecord(
        id=config_id,
        config_key=config_key,
        display_name="Noise Retail Buyer",
        strategy_engine=strategy_engine,
        version=1,
        config=config or {},
        enabled=True,
        created_at=_timestamp(),
        updated_at=_timestamp(),
    )


def _stats_value_randomization_config() -> dict[str, object]:
    return {
        "signal_weights": {
            "stats_form": 0.3,
            "minutes_security": 0.2,
            "market_value_gap": 0.2,
            "availability_risk": -0.25,
        },
        "stats_inputs": {
            "rating_weight": 0.35,
            "goals_weight": 0.2,
            "assists_weight": 0.15,
            "position_baseline_enabled": True,
        },
        "valuation": {
            "fair_value_blend": {
                "performance_implied_value": 0.45,
                "market_value_observation": 0.35,
                "current_stockball_price": 0.2,
            },
            "min_valuation_gap_to_buy": 0.08,
            "min_overvaluation_gap_to_sell": 0.12,
        },
        "sizing": {
            "base_cash_pct": 0.025,
            "confidence_multiplier": 1.2,
            "expected_return_multiplier": 0.8,
            "volatility_size_penalty": 0.6,
            "position_concentration_penalty": 0.7,
        },
        "execution": {
            "trade_probability": 0.35,
            "size_noise_pct": 0.15,
        },
    }


def _timestamp() -> datetime:
    return datetime(2026, 6, 13, 12, 0, tzinfo=UTC)


if __name__ == "__main__":
    unittest.main()
