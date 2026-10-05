from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
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
    def test_list_reserved_handles_loads_all_accounts_case_insensitively(self) -> None:
        cursor = FakeCursor([("Maya.Kerr",), ("user-1",)])
        repository = PostgresSyntheticTraderRepository("postgres://example")

        with patch(
            "app.synthetic_traders.repository.pooled_connection",
            return_value=FakeConnection(cursor),
        ):
            handles = repository.list_reserved_handles()

        self.assertEqual(handles, {"maya.kerr", "user-1"})
        self.assertIn("FROM accounts", cursor.executed[0][0])

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

        with patch(
            "app.synthetic_traders.repository.pooled_connection",
            return_value=FakeConnection(cursor),
        ):
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
            "app.synthetic_traders.repository.pooled_connection",
            return_value=FakeConnection(cursor),
        ):
            candidates = repository.load_candidate_instruments(portfolio, as_of)

        self.assertEqual(candidates[0].instrument_id, instrument_id)
        self.assertEqual(candidates[0].player_id, player_id)
        self.assertEqual(candidates[0].current_holding_quantity, Decimal("2"))

    def test_candidate_market_history_is_hydrated_once_then_refreshed_with_deltas(self) -> None:
        instrument_id = uuid4()
        player_id = uuid4()
        account_id = uuid4()
        initial_as_of = datetime(2026, 5, 22, 12, 0, tzinfo=UTC)
        next_as_of = initial_as_of + timedelta(minutes=10)
        initial_market_at = initial_as_of - timedelta(minutes=1)
        delta_market_at = initial_as_of + timedelta(minutes=5)
        initial_snapshot_id = uuid4()
        initial_trade_id = uuid4()

        def instrument_row(price: str) -> dict[str, object]:
            return {
                "id": str(instrument_id),
                "player_id": str(player_id),
                "symbol": "PLAYER-1",
                "display_name": "Player One",
                "current_price": Decimal(price),
                "trading_status": "ACTIVE",
                "club": "Arsenal",
                "position": "FWD",
            }

        initial_cursor = SequencedCursor(
            [
                [instrument_row("20")],
                [
                    {
                        "id": initial_snapshot_id,
                        "instrument_id": instrument_id,
                        "new_price": Decimal("20"),
                        "captured_at": initial_market_at,
                    }
                ],
                [
                    {
                        "id": initial_trade_id,
                        "instrument_id": instrument_id,
                        "side": "BUY",
                        "shares": Decimal("1"),
                        "gross_amount": Decimal("20"),
                        "account_id": account_id,
                        "executed_at": initial_market_at,
                    }
                ],
                [],
                [],
                [],
                [],
            ]
        )
        delta_cursor = SequencedCursor(
            [
                [instrument_row("21")],
                [
                    {
                        "id": initial_snapshot_id,
                        "instrument_id": instrument_id,
                        "new_price": Decimal("20"),
                        "captured_at": initial_market_at,
                    },
                    {
                        "id": uuid4(),
                        "instrument_id": instrument_id,
                        "new_price": Decimal("21"),
                        "captured_at": delta_market_at,
                    }
                ],
                [
                    {
                        "id": initial_trade_id,
                        "instrument_id": instrument_id,
                        "side": "BUY",
                        "shares": Decimal("1"),
                        "gross_amount": Decimal("20"),
                        "account_id": account_id,
                        "executed_at": initial_market_at,
                    },
                    {
                        "id": uuid4(),
                        "instrument_id": instrument_id,
                        "side": "BUY",
                        "shares": Decimal("1"),
                        "gross_amount": Decimal("21"),
                        "account_id": account_id,
                        "executed_at": delta_market_at,
                    }
                ],
                [],
                [],
                [],
                [],
            ]
        )
        portfolio = BotPortfolioContext(
            account_id=account_id,
            portfolio_id=uuid4(),
            cash_balance=Decimal("1000"),
            total_position_value=Decimal("0"),
            total_equity=Decimal("1000"),
            positions=(),
        )
        repository = PostgresSyntheticTraderRepository("postgres://example")

        with patch(
            "app.synthetic_traders.repository.pooled_connection",
            side_effect=[FakeConnection(initial_cursor), FakeConnection(delta_cursor)],
        ):
            initial = repository.load_candidate_instruments(portfolio, initial_as_of)
            refreshed = repository.load_candidate_instruments(portfolio, next_as_of)

        initial_price_query = initial_cursor.executed[1]
        delta_price_query = delta_cursor.executed[1]
        delta_trade_query = delta_cursor.executed[2]
        self.assertEqual(
            initial_price_query[1]["query_since"],
            initial_as_of - timedelta(days=30),
        )
        self.assertEqual(
            delta_price_query[1]["query_since"],
            initial_as_of - timedelta(minutes=5),
        )
        self.assertEqual(
            delta_trade_query[1]["query_since"],
            initial_as_of - timedelta(minutes=5),
        )
        self.assertEqual([point.price for point in initial[0].recent_prices], [Decimal("20")])
        self.assertEqual(
            [point.price for point in refreshed[0].recent_prices],
            [Decimal("20"), Decimal("21")],
        )
        self.assertEqual(len(refreshed[0].recent_trades), 2)


if __name__ == "__main__":
    unittest.main()


class MentionSpikeTests(unittest.TestCase):
    def test_spike_is_a_poisson_z_score_against_the_players_usual_rate(self) -> None:
        from app.synthetic_traders.repository import _mention_spike_zscore

        # Usually 2 mentions an hour; 8 this hour is three standard deviations up.
        self.assertAlmostEqual(_mention_spike_zscore(8, 1.0, 2.0), 6 / 2**0.5)
        # Exactly the usual rate is no spike.
        self.assertAlmostEqual(_mention_spike_zscore(2, 1.0, 2.0), 0.0)
        # A usually silent player is scored against a floor of one expected mention.
        self.assertAlmostEqual(_mention_spike_zscore(3, 1.0, 0.0), 3.0)
