from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from uuid import uuid4

from app.clients import SeedPlayerSharesRecord
from app.main import main


class SeedPlayerSharesCliTests(unittest.TestCase):
    def test_seed_player_shares_command_prints_summary(self) -> None:
        result = SeedPlayerSharesRecord(
            created_count=3,
            skipped_existing_count=2,
            market_value_priced_count=1,
            fallback_priced_count=2,
            created_instrument_ids=(uuid4(), uuid4(), uuid4()),
        )

        with patch.dict(
            os.environ,
            {
                "STOCKBALL_WORKER_DATABASE_URL": "postgresql://stockball.test/db",
                "STOCKBALL_WORKER_REDIS_URL": "redis://redis.test/0",
                "STOCKBALL_WORKER_TRADING_ENGINE_URL": "http://trading-engine.test",
            },
        ), patch("app.main.HttpTradingEngineClient") as client_class:
            client_class.return_value.seed_player_shares.return_value = result
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["seed-player-shares"])

        self.assertEqual(exit_code, 0)
        self.assertIn("3 created", stdout.getvalue())
        self.assertIn("2 fallback priced", stdout.getvalue())
        client_class.return_value.seed_player_shares.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
