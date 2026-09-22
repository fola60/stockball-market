from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from app.clients.trading_engine import TradingEngineClient
from app.orders.models import (
    ExecuteOrderCommand,
    OrderExecutionRecord,
    OrderQuoteRecord,
    SubmitOrderCommand,
)


class OrdersService:
    def __init__(
        self,
        trading_engine_client: TradingEngineClient,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._trading_engine_client = trading_engine_client
        self._request_id_factory = request_id_factory or _default_request_id

    def submit_order(self, command: SubmitOrderCommand) -> OrderExecutionRecord:
        execute_command = ExecuteOrderCommand(
            request_id=command.request_id or self._request_id_factory(),
            account_id=command.account_id,
            portfolio_id=command.portfolio_id,
            instrument_id=command.instrument_id,
            side=command.side,
            quantity=command.quantity,
        )
        return self._trading_engine_client.execute_order(execute_command)

    def quote_order(self, command: SubmitOrderCommand) -> OrderQuoteRecord:
        execute_command = ExecuteOrderCommand(
            request_id=command.request_id or self._request_id_factory(),
            account_id=command.account_id,
            portfolio_id=command.portfolio_id,
            instrument_id=command.instrument_id,
            side=command.side,
            quantity=command.quantity,
        )
        return self._trading_engine_client.quote_order(execute_command)


def _default_request_id() -> str:
    return str(uuid4())
