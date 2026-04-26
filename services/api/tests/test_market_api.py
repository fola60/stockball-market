from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.clients.trading_engine import TradingEngineClientError, TradingEngineUnavailableError
from app.instruments.models import (
    InstrumentRecord,
    InstrumentStatus,
    InstrumentType,
    PriceSnapshotReason,
    PriceSnapshotRecord,
)
from app.instruments.service import InstrumentsService
from app.main import create_app
from app.orders.models import ExecuteOrderCommand, OrderExecutionRecord, OrderSide
from app.orders.service import OrdersService
from app.portfolios.models import PortfolioRecord, PositionRecord
from app.portfolios.service import PortfoliosService


class FakeInstrumentsRepository:
    def __init__(self, instruments: list[InstrumentRecord], price_history: dict[UUID, list[PriceSnapshotRecord]]) -> None:
        self._instruments = {instrument.id: instrument for instrument in instruments}
        self._price_history = price_history

    def list_instruments(self) -> list[InstrumentRecord]:
        return list(self._instruments.values())

    def get_instrument(self, instrument_id: UUID) -> InstrumentRecord | None:
        return self._instruments.get(instrument_id)

    def list_price_history(self, instrument_id: UUID) -> list[PriceSnapshotRecord]:
        return list(self._price_history.get(instrument_id, []))


class FakePortfoliosRepository:
    def __init__(self, portfolios: list[PortfolioRecord]) -> None:
        self._portfolios = {portfolio.id: portfolio for portfolio in portfolios}

    def get_portfolio(self, portfolio_id: UUID) -> PortfolioRecord | None:
        return self._portfolios.get(portfolio_id)


class FakeTradingEngineClient:
    def __init__(
        self,
        response: OrderExecutionRecord | None = None,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.last_command: ExecuteOrderCommand | None = None

    def execute_order(self, command: ExecuteOrderCommand) -> OrderExecutionRecord:
        self.last_command = command
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


class MarketApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instrument_id = uuid4()
        self.portfolio_id = uuid4()
        self.account_id = uuid4()
        self.trade_id = uuid4()
        self.order_id = uuid4()

        instrument = InstrumentRecord(
            id=self.instrument_id,
            instrument_type=InstrumentType.PLAYER_SHARE,
            player_id=uuid4(),
            symbol="SEED-PLAYER",
            display_name="Seed Player Share",
            current_price="100.0000",
            quantity_outstanding="1000000.000000",
            price_impact_unit="0.010000",
            status=InstrumentStatus.ACTIVE,
            created_at=_timestamp(),
            updated_at=_timestamp(),
        )
        price_history = [
            PriceSnapshotRecord(
                id=uuid4(),
                instrument_id=self.instrument_id,
                old_price="100.0000",
                new_price="100.1000",
                reason=PriceSnapshotReason.TRADE_BUY,
                trade_id=self.trade_id,
                captured_at=_timestamp(),
            ),
            PriceSnapshotRecord(
                id=uuid4(),
                instrument_id=self.instrument_id,
                old_price="99.9000",
                new_price="100.0000",
                reason=PriceSnapshotReason.SEED,
                trade_id=None,
                captured_at=_timestamp(),
            ),
        ]

        portfolio = PortfolioRecord(
            id=self.portfolio_id,
            account_id=self.account_id,
            cash_balance="99000.0000",
            created_at=_timestamp(),
            updated_at=_timestamp(),
            positions=[
                PositionRecord(
                    id=uuid4(),
                    portfolio_id=self.portfolio_id,
                    instrument_id=self.instrument_id,
                    quantity="10.000000",
                    created_at=_timestamp(),
                    updated_at=_timestamp(),
                )
            ],
        )

        execution = OrderExecutionRecord(
            request_id="req_123",
            order_id=self.order_id,
            trade_id=self.trade_id,
            account_id=self.account_id,
            portfolio_id=self.portfolio_id,
            instrument_id=self.instrument_id,
            side=OrderSide.BUY,
            quantity="10.000000",
            execution_price="100.0000",
            gross_amount="1000.0000",
            cash_balance_after="99000.0000",
            position_quantity_after="10.000000",
            old_price="100.0000",
            new_price="100.1000",
            executed_at=_timestamp(),
        )

        self.instruments_repository = FakeInstrumentsRepository(
            instruments=[instrument],
            price_history={self.instrument_id: price_history},
        )
        self.portfolios_repository = FakePortfoliosRepository([portfolio])
        self.trading_engine_client = FakeTradingEngineClient(response=execution)
        self.client = TestClient(
            create_app(
                instruments_service=InstrumentsService(self.instruments_repository),
                portfolios_service=PortfoliosService(self.portfolios_repository),
                orders_service=OrdersService(
                    self.trading_engine_client, request_id_factory=lambda: "generated-request-id"
                ),
            )
        )

    def test_list_instruments_returns_seeded_instruments(self) -> None:
        response = self.client.get("/v1/instruments")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["id"], str(self.instrument_id))
        self.assertEqual(body[0]["instrument_type"], "PLAYER_SHARE")

    def test_get_instrument_returns_404_when_missing(self) -> None:
        response = self.client.get(f"/v1/instruments/{uuid4()}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "instrument_not_found")

    def test_list_price_history_returns_entries_for_instrument(self) -> None:
        response = self.client.get(f"/v1/instruments/{self.instrument_id}/price-history")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["reason"], "TRADE_BUY")
        self.assertEqual(body[1]["reason"], "SEED")

    def test_get_portfolio_returns_cash_and_positions(self) -> None:
        response = self.client.get(f"/v1/portfolios/{self.portfolio_id}")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], str(self.portfolio_id))
        self.assertEqual(body["cash_balance"], "99000.0000")
        self.assertEqual(body["positions"][0]["instrument_id"], str(self.instrument_id))

    def test_get_portfolio_returns_404_when_missing(self) -> None:
        response = self.client.get(f"/v1/portfolios/{uuid4()}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "portfolio_not_found")

    def test_create_order_generates_request_id_when_missing(self) -> None:
        response = self.client.post(
            "/v1/orders",
            json={
                "account_id": str(self.account_id),
                "portfolio_id": str(self.portfolio_id),
                "instrument_id": str(self.instrument_id),
                "side": "BUY",
                "quantity": "10.000000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(self.trading_engine_client.last_command)
        self.assertEqual(
            self.trading_engine_client.last_command.request_id, "generated-request-id"
        )
        self.assertEqual(response.json()["request_id"], "req_123")

    def test_create_order_passes_through_trading_engine_error(self) -> None:
        client = TestClient(
            create_app(
                orders_service=OrdersService(
                    FakeTradingEngineClient(
                        error=TradingEngineClientError(
                            409,
                            {
                                "code": "insufficient_cash",
                                "message": "portfolio has insufficient cash for this order.",
                            },
                        )
                    )
                )
            )
        )

        response = client.post(
            "/v1/orders",
            json={
                "request_id": "req_456",
                "account_id": str(self.account_id),
                "portfolio_id": str(self.portfolio_id),
                "instrument_id": str(self.instrument_id),
                "side": "BUY",
                "quantity": "10",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "insufficient_cash")

    def test_create_order_returns_502_when_trading_engine_is_unavailable(self) -> None:
        client = TestClient(
            create_app(
                orders_service=OrdersService(
                    FakeTradingEngineClient(error=TradingEngineUnavailableError("dial timeout"))
                )
            )
        )

        response = client.post(
            "/v1/orders",
            json={
                "request_id": "req_789",
                "account_id": str(self.account_id),
                "portfolio_id": str(self.portfolio_id),
                "instrument_id": str(self.instrument_id),
                "side": "SELL",
                "quantity": "1.5",
            },
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "trading_engine_unavailable")

    def test_create_order_rejects_quantity_more_precise_than_six_decimals(self) -> None:
        response = self.client.post(
            "/v1/orders",
            json={
                "account_id": str(self.account_id),
                "portfolio_id": str(self.portfolio_id),
                "instrument_id": str(self.instrument_id),
                "side": "BUY",
                "quantity": "1.0000001",
            },
        )

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(detail[0]["loc"], ["body", "quantity"])


def _timestamp() -> datetime:
    return datetime.now(tz=UTC)


if __name__ == "__main__":
    unittest.main()
