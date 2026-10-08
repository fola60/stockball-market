from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.common.images import IMAGE_RESPONSES, image_response
from app.common.schemas import ErrorResponse
from app.market.models import SparklineRange
from app.market.schemas import (
    MarketTradeResponse,
    MatchdayResponse,
    NewsItemResponse,
    SparklinesResponse,
)
from app.market.service import MarketService, TooManyInstrumentsError

router = APIRouter(prefix="/v1/market", tags=["market"])


def get_market_service(request: Request) -> MarketService:
    service = getattr(request.app.state, "market_service", None)
    if service is None:
        raise RuntimeError("market service is not configured")
    return service


@router.get(
    "/sparklines",
    response_model=SparklinesResponse,
    responses={422: {"model": ErrorResponse}},
)
def sparklines(
    request: Request,
    ids: str = Query(description="Comma-separated instrument IDs"),
    price_range: SparklineRange = Query(default=SparklineRange.WEEK, alias="range"),
) -> SparklinesResponse | JSONResponse:
    try:
        instrument_ids = [UUID(value.strip()) for value in ids.split(",") if value.strip()]
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"code": "invalid_instrument_id", "message": "ids must be instrument UUIDs"},
        )
    try:
        series = get_market_service(request).sparklines(instrument_ids, price_range)
    except TooManyInstrumentsError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"code": "too_many_instruments", "message": str(exc)},
        )
    return SparklinesResponse(
        range=price_range,
        series={str(instrument_id): prices for instrument_id, prices in series.items()},
    )


@router.get("/matchday", response_model=MatchdayResponse)
def matchday(request: Request) -> MatchdayResponse:
    return MatchdayResponse.from_record(get_market_service(request).matchday())


@router.get("/trades", response_model=list[MarketTradeResponse])
def recent_trades(
    request: Request,
    limit: int = Query(default=5, ge=1, le=20),
    hours: int = Query(default=3, ge=1, le=24),
) -> list[MarketTradeResponse]:
    trades = get_market_service(request).recent_trades(limit, hours)
    return [MarketTradeResponse.from_record(trade) for trade in trades]


@router.get("/news", response_model=list[NewsItemResponse])
def news(request: Request, limit: int = Query(default=3, ge=1, le=10)) -> list[NewsItemResponse]:
    return [NewsItemResponse.from_record(item) for item in get_market_service(request).news(limit)]


@router.get("/teams/{team_id}/badge", response_class=Response, responses=IMAGE_RESPONSES)
def team_badge(
    request: Request, team_id: str = Path(pattern=r"^[0-9]{1,12}$")
) -> Response:
    badge = get_market_service(request).team_badge(team_id)
    return image_response(request, badge, "team_badge_not_found", "no badge is available for this team")
