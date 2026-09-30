from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from app.clients.trading_engine import (
    ApplyTopupCommand,
    ExecuteOrderCommand,
    HttpTradingEngineClient,
    InitialSupplyAllocation,
    IssueInitialSupplyCommand,
    LedgerReason,
    OrderSide,
    SetPreMarketPriceCommand,
    TradingEngineClientError,
    TradingEngineUnavailableError,
)


class TradingEngineClientTests(unittest.TestCase):
    def test_execute_order_posts_contract_payload(self) -> None:
        account_id = uuid4()
        portfolio_id = uuid4()
        instrument_id = uuid4()
        request: httpx.Request | None = None

        def handler(incoming: httpx.Request) -> httpx.Response:
            nonlocal request
            request = incoming
            return httpx.Response(
                200,
                json={
                    "request_id": "req_123",
                    "order_id": str(uuid4()),
                    "trade_id": str(uuid4()),
                    "account_id": str(account_id),
                    "portfolio_id": str(portfolio_id),
                    "instrument_id": str(instrument_id),
                    "side": "BUY",
                    "quantity": "10.000000",
                    "execution_price": "100.0000",
                    "gross_amount": "1000.0000",
                    "cash_balance_after": "99000.0000",
                    "position_quantity_after": "10.000000",
                    "old_price": "100.0000",
                    "new_price": "100.1000",
                    "executed_at": datetime(2026, 4, 22, 12, 0, tzinfo=UTC).isoformat(),
                },
            )

        client = HttpTradingEngineClient(
            base_url="http://trading-engine.test",
            transport=httpx.MockTransport(handler),
        )

        result = client.execute_order(
            ExecuteOrderCommand(
                request_id="req_123",
                account_id=account_id,
                portfolio_id=portfolio_id,
                instrument_id=instrument_id,
                side=OrderSide.BUY,
                quantity="10.000000",
            )
        )

        assert request is not None
        self.assertEqual(request.url.path, "/internal/v1/orders/execute")
        self.assertEqual(
            json.loads(request.content.decode("utf-8")),
            {
                "request_id": "req_123",
                "account_id": str(account_id),
                "portfolio_id": str(portfolio_id),
                "instrument_id": str(instrument_id),
                "side": "BUY",
                "quantity": "10.000000",
            },
        )
        self.assertEqual(result.request_id, "req_123")
        self.assertEqual(result.side, OrderSide.BUY)

    def test_apply_topup_parses_ledger_entry(self) -> None:
        account_id = uuid4()
        portfolio_id = uuid4()

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/internal/v1/ledger/topups/apply")
            return httpx.Response(
                200,
                json={
                    "id": str(uuid4()),
                    "account_id": str(account_id),
                    "portfolio_id": str(portfolio_id),
                    "trade_id": None,
                    "reason": "WEEKLY_TOPUP",
                    "amount_delta": "250.0000",
                    "balance_after": "10250.0000",
                    "source_request_id": "topup:weekly:2026-04-20",
                    "created_at": datetime(2026, 4, 22, 12, 5, tzinfo=UTC).isoformat(),
                },
            )

        client = HttpTradingEngineClient(
            base_url="http://trading-engine.test",
            transport=httpx.MockTransport(handler),
        )

        result = client.apply_topup(
            ApplyTopupCommand(
                request_id="topup:weekly:2026-04-20",
                account_id=account_id,
                portfolio_id=portfolio_id,
                amount="250.0000",
                reason=LedgerReason.WEEKLY_TOPUP,
            )
        )

        self.assertEqual(result.reason, LedgerReason.WEEKLY_TOPUP)
        self.assertEqual(result.amount_delta, "250.0000")

    def test_seed_player_shares_posts_to_seed_endpoint(self) -> None:
        instrument_id = uuid4()
        request: httpx.Request | None = None

        def handler(incoming: httpx.Request) -> httpx.Response:
            nonlocal request
            request = incoming
            return httpx.Response(
                200,
                json={
                    "created_count": 1,
                    "skipped_existing_count": 2,
                    "market_value_priced_count": 1,
                    "fallback_priced_count": 0,
                    "created_instrument_ids": [str(instrument_id)],
                },
            )

        client = HttpTradingEngineClient(
            base_url="http://trading-engine.test",
            transport=httpx.MockTransport(handler),
        )

        result = client.seed_player_shares()

        assert request is not None
        self.assertEqual(request.url.path, "/internal/v1/instruments/player-shares/seed")
        self.assertEqual(json.loads(request.content.decode("utf-8")), {})
        self.assertEqual(result.created_count, 1)
        self.assertEqual(result.skipped_existing_count, 2)
        self.assertEqual(result.created_instrument_ids, (instrument_id,))

    def test_issue_initial_supply_posts_allocations(self) -> None:
        instrument_id, portfolio_id = uuid4(), uuid4()
        requests: list[httpx.Request] = []

        def handler(incoming: httpx.Request) -> httpx.Response:
            requests.append(incoming)
            return httpx.Response(
                200,
                json={"request_id": "supply-1", "instrument_count": 1, "position_count": 1},
            )

        client = HttpTradingEngineClient(
            "http://trading-engine.test", transport=httpx.MockTransport(handler)
        )
        client.issue_initial_supply(
            IssueInitialSupplyCommand(
                request_id="supply-1",
                allocations=(InitialSupplyAllocation(instrument_id, portfolio_id, "100"),),
            )
        )

        self.assertEqual(requests[0].url.path, "/internal/v1/positions/initial-supply/issue")
        self.assertEqual(
            json.loads(requests[0].content),
            {
                "request_id": "supply-1",
                "allocations": [
                    {
                        "instrument_id": str(instrument_id),
                        "portfolio_id": str(portfolio_id),
                        "quantity": "100",
                    }
                ],
            },
        )

    def test_set_pre_market_price_parses_result(self) -> None:
        instrument_id = uuid4()
        requests: list[httpx.Request] = []

        def handler(incoming: httpx.Request) -> httpx.Response:
            requests.append(incoming)
            return httpx.Response(
                200,
                json={
                    "instrument_id": str(instrument_id),
                    "old_price": "10.0000",
                    "new_price": "12.5",
                },
            )

        client = HttpTradingEngineClient(
            "http://trading-engine.test", transport=httpx.MockTransport(handler)
        )
        result = client.set_pre_market_price(
            SetPreMarketPriceCommand("price-1", instrument_id, "12.5")
        )

        self.assertEqual(requests[0].url.path, "/internal/v1/instruments/pre-market-price/set")
        self.assertEqual(
            json.loads(requests[0].content),
            {"request_id": "price-1", "instrument_id": str(instrument_id), "new_price": "12.5"},
        )
        self.assertEqual(result.old_price, "10.0000")

    def test_http_error_is_retryable_unavailable_error(self) -> None:
        client = HttpTradingEngineClient(
            base_url="http://trading-engine.test",
            transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("boom"))),
        )

        with self.assertRaises(TradingEngineUnavailableError):
            client.execute_order(
                ExecuteOrderCommand(
                    request_id="req_123",
                    account_id=uuid4(),
                    portfolio_id=uuid4(),
                    instrument_id=uuid4(),
                    side=OrderSide.BUY,
                    quantity="1.000000",
                )
            )

    def test_error_response_raises_client_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                409,
                json={
                    "code": "idempotency_in_progress",
                    "message": "request is still being processed",
                },
            )

        client = HttpTradingEngineClient(
            base_url="http://trading-engine.test",
            transport=httpx.MockTransport(handler),
        )

        with self.assertRaises(TradingEngineClientError) as context:
            client.apply_topup(
                ApplyTopupCommand(
                    request_id="topup:weekly",
                    account_id=uuid4(),
                    portfolio_id=uuid4(),
                    amount="250.0000",
                    reason=LedgerReason.WEEKLY_TOPUP,
                )
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.body["code"], "idempotency_in_progress")


if __name__ == "__main__":
    unittest.main()
