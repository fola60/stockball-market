from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dev_operations.router import router


class FakeTradeRepository:
    def __init__(self) -> None:
        self.list_args = None
        self.trade = None

    def list_trades(self, **kwargs):
        self.list_args = kwargs
        return {
            "items": [],
            "total": 0,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
            "summary": {"total": 0},
        }

    def get_trade_details(self, trade_id):
        return self.trade if self.trade and self.trade["id"] == str(trade_id) else None


class DevTradeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeTradeRepository()
        app = FastAPI()
        app.state.dev_operations_service = SimpleNamespace(repository=self.repository)
        app.include_router(router)
        self.client = TestClient(app)

    def test_list_trades_passes_pagination_and_filters(self) -> None:
        response = self.client.get(
            "/internal/v1/dev/trades",
            params={
                "limit": 25,
                "offset": 50,
                "account_type": "SYNTHETIC_TRADER",
                "side": "BUY",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.repository.list_args,
            {
                "limit": 25,
                "offset": 50,
                "account_type": "SYNTHETIC_TRADER",
                "side": "BUY",
            },
        )

    def test_list_trades_rejects_invalid_filters(self) -> None:
        response = self.client.get(
            "/internal/v1/dev/trades", params={"account_type": "UNKNOWN"}
        )

        self.assertEqual(response.status_code, 422)

    def test_get_trade_details_returns_joined_record(self) -> None:
        trade_id = uuid4()
        self.repository.trade = {"id": str(trade_id), "account_type": "USER"}

        response = self.client.get(f"/internal/v1/dev/trades/{trade_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.repository.trade)

    def test_get_trade_details_returns_404_when_missing(self) -> None:
        response = self.client.get(f"/internal/v1/dev/trades/{uuid4()}")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
