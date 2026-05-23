from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

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


if __name__ == "__main__":
    unittest.main()
