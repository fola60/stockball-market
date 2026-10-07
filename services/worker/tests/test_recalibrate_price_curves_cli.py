from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from app.clients.trading_engine import RecalibratePriceCurvesRecord, TradingEngineClientError
from app.entrypoints.cli import main


class _Engine:
    def __init__(self, error: Exception | None = None) -> None:
        self.commands = []
        self.error = error

    def recalibrate_price_curves(self, command):
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return RecalibratePriceCurvesRecord(
            request_id=command.request_id,
            dry_run=command.dry_run,
            full_supply_price_multiplier=command.full_supply_price_multiplier,
            curve_depth_divisor=command.curve_depth_divisor,
            instrument_count=421,
            reset_net_demand_count=380,
            max_reset_demand_ratio="0.0425",
            previous_min_multiplier="4.000000",
            previous_max_multiplier="4.000000",
        )


class RecalibratePriceCurvesCliTests(unittest.TestCase):
    def _run(self, engine: _Engine, *args: str) -> tuple[int, str]:
        output = io.StringIO()
        with (
            patch("app.entrypoints.commands.market.Settings.from_env"),
            patch("app.entrypoints.commands.market.configure_logging"),
            patch("app.entrypoints.commands.market.trading_engine_client", return_value=engine),
            redirect_stdout(output),
        ):
            code = main(["recalibrate-price-curves", *args])
        return code, output.getvalue()

    def test_is_a_dry_run_unless_applied(self) -> None:
        engine = _Engine()
        code, output = self._run(
            engine, "--multiplier", "20", "--depth-divisor", "15", "--reason", "volatility"
        )

        self.assertEqual(code, 0)
        self.assertTrue(engine.commands[0].dry_run)
        self.assertRegex(engine.commands[0].request_id, r"^price-curves:\d{4}-\d{2}-\d{2}:20x:15$")
        self.assertIn("would rebase 421 price curves", output)
        self.assertIn("nothing was written", output)

    def test_apply_writes_with_the_given_request_id(self) -> None:
        engine = _Engine()
        code, output = self._run(
            engine,
            "--multiplier", "20",
            "--depth-divisor", "15",
            "--reason", "volatility",
            "--request-id", "curves-oct",
            "--apply",
        )

        self.assertEqual(code, 0)
        self.assertFalse(engine.commands[0].dry_run)
        self.assertEqual(engine.commands[0].request_id, "curves-oct")
        self.assertIn("rebased 421 price curves to 20x", output)

    def test_reports_why_the_engine_refused(self) -> None:
        engine = _Engine(
            TradingEngineClientError(
                422,
                {
                    "code": "invalid_curve_calibration",
                    "message": "price curve calibration is invalid.",
                    "details": {"reason": "curve_depth_divisor must be at least 1: 0.5"},
                },
            )
        )
        code, output = self._run(
            engine, "--multiplier", "20", "--depth-divisor", "0.5", "--reason", "x"
        )

        self.assertEqual(code, 1)
        self.assertIn("curve_depth_divisor must be at least 1", output)


if __name__ == "__main__":
    unittest.main()
