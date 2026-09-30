from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from app.main import main
from app.seeding.portfolios import (
    RESERVE_PORTFOLIO_ID,
    BootstrapAllocationPlan,
    BootstrapPositionAllocation,
)


class BootstrapSyntheticPortfoliosCliTests(unittest.TestCase):
    def test_dry_run_prints_concise_allocation_summary(self) -> None:
        bot_id = uuid4()
        instrument_id = uuid4()
        result = BootstrapAllocationPlan(
            seed=20260903,
            selected_bot_ids=(bot_id,),
            allocations=(
                BootstrapPositionAllocation(
                    instrument_id=instrument_id,
                    portfolio_id=uuid4(),
                    bot_id=bot_id,
                    quantity=90,
                    seed_price=Decimal("10"),
                ),
                BootstrapPositionAllocation(
                    instrument_id=instrument_id,
                    portfolio_id=RESERVE_PORTFOLIO_ID,
                    bot_id=None,
                    quantity=10,
                    seed_price=Decimal("10"),
                    is_reserve=True,
                ),
            ),
            instruments_processed=1,
            skipped_instruments=(("OLD", "supply already fully owned"),),
        )

        with patch.dict(
            os.environ,
            {
                "STOCKBALL_WORKER_DATABASE_URL": "postgresql://stockball.test/db",
                "STOCKBALL_WORKER_TRADING_ENGINE_URL": "http://trading-engine.test",
            },
        ), patch("app.entrypoints.commands.market.SyntheticPortfolioBootstrapService") as service_class:
            service_class.return_value.bootstrap.return_value = result
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "bootstrap-synthetic-portfolios",
                        "--all-active-synthetic-bots",
                        "--seed",
                        "20260903",
                        "--dry-run",
                    ]
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("seed=20260903", output)
        self.assertIn("bots=1", output)
        self.assertIn("instruments=1", output)
        self.assertIn("bot_shares=90", output)
        self.assertIn("reserve_shares=10", output)
        self.assertIn("positions=2", output)
        self.assertIn("skipped OLD: supply already fully owned", output)
        command = service_class.return_value.bootstrap.call_args.kwargs
        self.assertTrue(command["all_active_synthetic_bots"])
        self.assertTrue(command["dry_run"])
        self.assertEqual(command["seed"], 20260903)


if __name__ == "__main__":
    unittest.main()
