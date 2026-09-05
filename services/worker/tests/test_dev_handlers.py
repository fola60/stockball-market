from __future__ import annotations

import unittest
from decimal import Decimal
from uuid import uuid4

from app.jobs.dev_handlers import bootstrap_portfolios_handler
from app.synthetic_traders.bootstrap import (
    RESERVE_PORTFOLIO_ID,
    BootstrapAllocationPlan,
    BootstrapPositionAllocation,
)


class FakeBootstrapService:
    def bootstrap(self, **kwargs):
        self.kwargs = kwargs
        bot_id = uuid4()
        return BootstrapAllocationPlan(
            seed=42,
            selected_bot_ids=(bot_id,),
            allocations=(
                BootstrapPositionAllocation(
                    instrument_id=uuid4(),
                    portfolio_id=uuid4(),
                    bot_id=bot_id,
                    quantity=90,
                    seed_price=Decimal("10"),
                ),
                BootstrapPositionAllocation(
                    instrument_id=uuid4(),
                    portfolio_id=RESERVE_PORTFOLIO_ID,
                    bot_id=None,
                    quantity=10,
                    seed_price=Decimal("10"),
                    is_reserve=True,
                ),
            ),
            instruments_processed=1,
            skipped_instruments=(),
            bot_cash_balances=(Decimal("100000"),),
        )


class DevHandlerTests(unittest.TestCase):
    def test_bootstrap_dry_run_reports_projection_without_successful_writes(self) -> None:
        service = FakeBootstrapService()

        result = bootstrap_portfolios_handler(service)(
            {"all_active_synthetic_bots": True, "seed": 42, "dry_run": True}
        )

        self.assertEqual(result.successful_items, 0)
        self.assertEqual(result.metrics["projected_positions"], 2)
        self.assertEqual(result.metrics["bot_positions"], 1)
        self.assertEqual(result.metrics["reserve_positions"], 1)
        self.assertEqual(result.metrics["total_bot_cash"], "100000")
        self.assertEqual(result.metrics["average_bot_cash"], "100000")
        self.assertTrue(result.metrics["dry_run"])


if __name__ == "__main__":
    unittest.main()
