from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_principal
from app.auth.models import CurrentPrincipal
from app.clients.trading_engine import (
    TradingEngineClientError,
    TradingEngineUnavailableError,
)
from app.common.schemas import ErrorResponse
from app.orders.models import SubmitOrderCommand
from app.orders.schemas import CreateOrderRequest, OrderExecutionResponse, OrderQuoteResponse
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
    payload: CreateOrderRequest,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> OrderExecutionResponse | JSONResponse:
    service = get_orders_service(request)
    try:
        result = service.submit_order(
            SubmitOrderCommand(
                request_id=payload.request_id,
                account_id=principal.account_id,
                portfolio_id=principal.portfolio_id,
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


@router.post(
    "/quote",
    response_model=OrderQuoteResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def quote_order(
    payload: CreateOrderRequest,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> OrderQuoteResponse | JSONResponse:
    service = get_orders_service(request)
    try:
        result = service.quote_order(
            SubmitOrderCommand(
                request_id=payload.request_id,
                account_id=principal.account_id,
                portfolio_id=principal.portfolio_id,
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
            content={"code": "trading_engine_unavailable", "message": str(exc)},
        )
    return OrderQuoteResponse.from_record(result)
