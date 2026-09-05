from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from app.synthetic_traders.models import BotPortfolioContext, BotPositionContext
from app.synthetic_traders.repository import PostgresSyntheticTraderRepository


class FakeCursor:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.executed: list[tuple[str, object]] = []

    def execute(self, query: str, params=None) -> None:
        self.executed.append((query, params))

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self, cursor_factory=None):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def close(self) -> None:
        return None


class SequencedCursor(FakeCursor):
    def __init__(self, result_sets: list[list[object]]) -> None:
        super().__init__([])
        self.result_sets = list(result_sets)

    def fetchall(self):
        return self.result_sets.pop(0)


class SyntheticTraderRepositoryTests(unittest.TestCase):
    def test_list_due_bots_loads_active_due_rows(self) -> None:
        bot_id = uuid4()
        account_id = uuid4()
        config_id = uuid4()
        portfolio_id = uuid4()
        row = {
            "id": bot_id,
            "account_id": account_id,
            "portfolio_id": portfolio_id,
            "config_id": config_id,
            "bot_key": "bot-1",
            "display_name": "Bot One",
            "status": "ACTIVE",
            "config_overrides": {},
            "last_ticked_at": None,
            "next_tick_after": datetime(2026, 5, 22, 11, 30, tzinfo=UTC),
            "created_at": datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
            "updated_at": datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
        }
        cursor = FakeCursor([row])
        repository = PostgresSyntheticTraderRepository("postgres://example")

        with patch("app.synthetic_traders.repository.psycopg2.connect", return_value=FakeConnection(cursor)):
            bots = repository.list_due_bots(datetime(2026, 5, 22, 12, 0, tzinfo=UTC))

        self.assertEqual(len(bots), 1)
        self.assertEqual(bots[0].id, bot_id)
        self.assertEqual(bots[0].portfolio_id, portfolio_id)
        self.assertEqual(bots[0].config_id, config_id)
        self.assertIn("synthetic_trader_bots", cursor.executed[0][0])

    def test_load_betting_markets_returns_window_endpoints_and_depth(self) -> None:
        player_id = uuid4()
        baseline_at = datetime(2026, 5, 22, 11, 0, tzinfo=UTC)
        latest_at = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
        common = {
            "player_id": str(player_id),
            "provider_event_id": "event-1",
            "canonical_selection_key": "GOALSCORER|FULL_MATCH|ANYTIME|-|player-one",
            "market_type": "GOALSCORER",
            "outcome_type": "ANYTIME",
            "line": None,
            "kickoff_at": latest_at,
            "observation_count": 12,
        }
        cursor = FakeCursor(
            [
                {
                    **common,
                    "decimal_odds": Decimal("3.0"),
                    "implied_probability": Decimal("0.3333"),
                    "observed_at": baseline_at,
                },
                {
                    **common,
                    "decimal_odds": Decimal("2.0"),
                    "implied_probability": Decimal("0.5"),
                    "observed_at": latest_at,
                },
            ]
        )
        repository = PostgresSyntheticTraderRepository("postgres://example")

        contexts = repository._load_betting_markets(
            cursor,
            [str(player_id)],
            baseline_at,
            latest_at,
        )

        self.assertEqual(len(contexts[str(player_id)].quotes), 2)
        self.assertEqual(contexts[str(player_id)].quotes[-1].observation_count, 12)
        self.assertIn("baseline_row_number = 1", cursor.executed[0][0])
        self.assertEqual(cursor.executed[0][1]["as_of"], latest_at)

    def test_candidate_ids_are_uuids_and_match_portfolio_holdings(self) -> None:
        instrument_id = uuid4()
        player_id = uuid4()
        as_of = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
        cursor = SequencedCursor(
            [
                [
                    {
                        "id": str(instrument_id),
                        "player_id": str(player_id),
                        "symbol": "PLAYER-1",
                        "display_name": "Player One",
                        "current_price": Decimal("20"),
                        "trading_status": "ACTIVE",
                        "club": "Arsenal",
                        "position": "FWD",
                    }
                ],
                [],
                [],
                [],
                [],
            ]
        )
        portfolio = BotPortfolioContext(
            account_id=uuid4(),
            portfolio_id=uuid4(),
            cash_balance=Decimal("1000"),
            total_position_value=Decimal("40"),
            total_equity=Decimal("1040"),
            positions=(
                BotPositionContext(
                    instrument_id=instrument_id,
                    player_id=player_id,
                    club="Arsenal",
                    quantity=Decimal("2"),
                    current_price=Decimal("20"),
                    market_value=Decimal("40"),
                ),
            ),
        )
        repository = PostgresSyntheticTraderRepository("postgres://example")

        with patch(
            "app.synthetic_traders.repository.psycopg2.connect",
            return_value=FakeConnection(cursor),
        ):
            candidates = repository.load_candidate_instruments(portfolio, as_of)

        self.assertEqual(candidates[0].instrument_id, instrument_id)
        self.assertEqual(candidates[0].player_id, player_id)
        self.assertEqual(candidates[0].current_holding_quantity, Decimal("2"))


if __name__ == "__main__":
    unittest.main()
