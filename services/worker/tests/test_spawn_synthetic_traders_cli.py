from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from uuid import uuid4

from app.main import main
from app.synthetic_traders import (
    SpawnedSyntheticTrader,
    SpawnNameStyle,
    SpawnSyntheticTraderBatchResult,
    StrategyEngine,
)


class SpawnSyntheticTradersCliTests(unittest.TestCase):
    def test_spawn_synthetic_traders_command_prints_summary(self) -> None:
        result = SpawnSyntheticTraderBatchResult(
            config_key="NOISE_RETAIL_BUYER",
            requested_count=2,
            spawned=(
                SpawnedSyntheticTrader(
                    account_id=uuid4(),
                    portfolio_id=uuid4(),
                    bot_id=uuid4(),
                    config_id=uuid4(),
                    handle="noise-buyer-001",
                    bot_key="noise-buyer-001",
                    display_name="Noise Buyer 001",
                ),
                SpawnedSyntheticTrader(
                    account_id=uuid4(),
                    portfolio_id=uuid4(),
                    bot_id=uuid4(),
                    config_id=uuid4(),
                    handle="noise-buyer-002",
                    bot_key="noise-buyer-002",
                    display_name="Noise Buyer 002",
                ),
            ),
        )

        with patch.dict(
            os.environ,
            {
                "STOCKBALL_WORKER_DATABASE_URL": "postgresql://stockball.test/db",
                "STOCKBALL_WORKER_REDIS_URL": "redis://redis.test/0",
                "STOCKBALL_WORKER_TRADING_ENGINE_URL": "http://trading-engine.test",
                "STOCKBALL_WORKER_API_URL": "http://api.test",
            },
        ), patch("app.entrypoints.factories.SyntheticTraderSpawner") as spawner_class:
            spawner_class.return_value.spawn.return_value = result
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "spawn-synthetic-traders",
                        "--config-key",
                        "NOISE_RETAIL_BUYER",
                        "--count",
                        "2",
                        "--handle-prefix",
                        "noise-buyer",
                        "--display-name-prefix",
                        "Noise Buyer",
                        "--name-style",
                        "NUMBERED",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("spawned 2/2 synthetic traders", stdout.getvalue())
        self.assertIn("noise-buyer-001", stdout.getvalue())
        spawn_command = spawner_class.return_value.spawn.call_args.args[0]
        self.assertEqual(spawn_command.config_key, "NOISE_RETAIL_BUYER")
        self.assertIsNone(spawn_command.strategy_engine)
        self.assertEqual(spawn_command.name_style, SpawnNameStyle.NUMBERED)
        self.assertIsNone(spawn_command.random_seed)
        self.assertEqual(spawn_command.count, 2)
        self.assertEqual(spawn_command.handle_prefix, "noise-buyer")

    def test_spawn_synthetic_traders_accepts_strategy_engine_selector(self) -> None:
        result = SpawnSyntheticTraderBatchResult(
            config_key="STATS_VALUE_CONSERVATIVE",
            requested_count=1,
            spawned=(
                SpawnedSyntheticTrader(
                    account_id=uuid4(),
                    portfolio_id=uuid4(),
                    bot_id=uuid4(),
                    config_id=uuid4(),
                    handle="stats-value-001",
                    bot_key="stats-value-001",
                    display_name="Stats Value 001",
                ),
            ),
        )

        with patch.dict(
            os.environ,
            {
                "STOCKBALL_WORKER_DATABASE_URL": "postgresql://stockball.test/db",
                "STOCKBALL_WORKER_REDIS_URL": "redis://redis.test/0",
                "STOCKBALL_WORKER_TRADING_ENGINE_URL": "http://trading-engine.test",
                "STOCKBALL_WORKER_API_URL": "http://api.test",
            },
        ), patch("app.entrypoints.factories.SyntheticTraderSpawner") as spawner_class:
            spawner_class.return_value.spawn.return_value = result
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "spawn-synthetic-traders",
                        "--strategy-engine",
                        "STATS_VALUE",
                        "--count",
                        "1",
                        "--random-seed",
                        "20260613",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("using config STATS_VALUE_CONSERVATIVE", stdout.getvalue())
        spawn_command = spawner_class.return_value.spawn.call_args.args[0]
        self.assertIsNone(spawn_command.config_key)
        self.assertEqual(spawn_command.strategy_engine, StrategyEngine.STATS_VALUE)
        self.assertEqual(spawn_command.name_style, SpawnNameStyle.PERSONA)
        self.assertEqual(spawn_command.random_seed, 20260613)
        self.assertEqual(spawn_command.count, 1)


if __name__ == "__main__":
    unittest.main()
