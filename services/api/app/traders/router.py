from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from app.common.schemas import ErrorResponse
from app.traders.models import LeaderboardFilter
from app.traders.schemas import LeaderboardResponse, TraderProfileResponse
from app.traders.service import MAX_PAGE_SIZE, TraderNotFoundError, TradersService

router = APIRouter(prefix="/v1/traders", tags=["traders"])


def get_traders_service(request: Request) -> TradersService:
    service = getattr(request.app.state, "traders_service", None)
    if service is None:
        raise RuntimeError("traders service is not configured")
    return service


@router.get("/leaderboard", response_model=LeaderboardResponse)
def leaderboard(
    request: Request,
    filter: LeaderboardFilter = LeaderboardFilter.ALL,
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> LeaderboardResponse:
    page = get_traders_service(request).leaderboard(filter, limit, offset)
    return LeaderboardResponse.from_record(page)


@router.get(
    "/{account_id}",
    response_model=TraderProfileResponse,
    responses={404: {"model": ErrorResponse}},
)
def trader_profile(account_id: UUID, request: Request) -> TraderProfileResponse | JSONResponse:
    try:
        profile = get_traders_service(request).profile(account_id)
    except TraderNotFoundError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": "trader_not_found", "message": str(exc)},
        )
    return TraderProfileResponse.from_record(profile)
