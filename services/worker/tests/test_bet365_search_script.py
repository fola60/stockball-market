from __future__ import annotations

import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from app.ingestion.betting_markets import Bet365IngestionError, BettingMarketObservation
from scripts.test_bet365_search import main


def _observation(selection_key: str, odds: str) -> BettingMarketObservation:
    decimal_odds = Decimal(odds)
    return BettingMarketObservation(
        provider="BET365",
        provider_event_id="196564288",
        fixture_provider_id=None,
        market_key="1X2",
        selection_key=selection_key,
        decimal_odds=decimal_odds,
        implied_probability=Decimal("1") / decimal_odds,
        observed_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        source_url="https://www.bet365.com/#/AC/B1/C1/D8/E196564288/F3/I1/",
        raw_payload={
            "home_team": "Bournemouth",
            "away_team": "Everton",
            "selection": selection_key,
            "display_odds": odds,
        },
    )


class Bet365SearchScriptTests(unittest.TestCase):
    @patch("scripts.test_bet365_search.Bet365Client")
    def test_uses_production_client_and_prints_normalized_results(self, client_type) -> None:
        client_type.return_value.list_pre_match_1x2.return_value = [
            _observation("HOME", "2.2"),
            _observation("DRAW", "3.5"),
            _observation("AWAY", "3.25"),
        ]
        output = StringIO()

        with redirect_stdout(output):
            result = main(
                [
                    "--league",
                    "PL",
                    "--max-matches",
                    "3",
                ]
            )

        self.assertEqual(result, 0)
        client_type.return_value.list_pre_match_1x2.assert_called_once_with("PL")
        self.assertTrue(client_type.call_args.kwargs["policy_acknowledged"])
        self.assertTrue(client_type.call_args.kwargs["browser_enabled"])
        self.assertEqual(client_type.call_args.kwargs["max_matches"], 3)
        self.assertIsNone(client_type.call_args.kwargs["browser_user_data_dir"])
        self.assertIsNone(client_type.call_args.kwargs["browser_profile_directory"])
        self.assertIn("isolated temporary Chrome profile", output.getvalue())
        self.assertIn("Bournemouth vs Everton", output.getvalue())
        self.assertIn("event_id=196564288", output.getvalue())
        self.assertIn("AWAY", output.getvalue())

    @patch("scripts.test_bet365_search.Bet365Client")
    def test_reports_client_error_without_traceback(self, client_type) -> None:
        client_type.return_value.list_pre_match_1x2.side_effect = Bet365IngestionError("blocked")
        error_output = StringIO()

        with redirect_stdout(StringIO()), redirect_stderr(error_output):
            result = main(
                [
                    "--user-data-dir",
                    "/tmp/chrome",
                    "--profile",
                    "Default",
                ]
            )

        self.assertEqual(result, 1)
        self.assertIn("Bet365 fetch failed: blocked", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
