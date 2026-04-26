from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.clients.trading_engine import (
    TradingEngineClientError,
    TradingEngineUnavailableError,
)
from app.common.schemas import ErrorResponse
from app.orders.models import SubmitOrderCommand
from app.orders.schemas import CreateOrderRequest, OrderExecutionResponse
from app.orders.service import OrdersService


router = APIRouter(prefix="/v1/orders", tags=["orders"])


def get_orders_service(request: Request) -> OrdersService:
    service = getattr(request.app.state, "orders_service", None)
    if service is None:
        raise RuntimeError("orders service is not configured")
    return service


@router.post(
    "",
    response_model=OrderExecutionResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
def create_order(
    payload: CreateOrderRequest, request: Request
) -> OrderExecutionResponse | JSONResponse:
    service = get_orders_service(request)
    try:
        result = service.submit_order(
            SubmitOrderCommand(
                request_id=payload.request_id,
                account_id=payload.account_id,
                portfolio_id=payload.portfolio_id,
                instrument_id=payload.instrument_id,
                side=payload.side,
                quantity=payload.quantity,
            )
        )
    except TradingEngineClientError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.body)
    except TradingEngineUnavailableError as exc:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "code": "trading_engine_unavailable",
                "message": str(exc),
            },
        )

    return OrderExecutionResponse.from_record(result)
