from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_current_principal
from app.auth.models import CurrentPrincipal
from app.common.schemas import ErrorResponse
from app.portfolios.schemas import PortfolioActivityResponse, PortfolioResponse
from app.portfolios.service import PortfolioNotFoundError, PortfoliosService

router = APIRouter(prefix="/v1/portfolios", tags=["portfolios"])


def get_portfolios_service(request: Request) -> PortfoliosService:
    service = getattr(request.app.state, "portfolios_service", None)
    if service is None:
        raise RuntimeError("portfolios service is not configured")
    return service


@router.get(
    "/{portfolio_id}",
    response_model=PortfolioResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_portfolio(
    portfolio_id: UUID,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> PortfolioResponse | JSONResponse:
    if portfolio_id != principal.portfolio_id:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"code": "portfolio_forbidden", "message": "You cannot access this portfolio."},
        )
    service = get_portfolios_service(request)
    try:
        portfolio = service.get_portfolio(portfolio_id)
    except PortfolioNotFoundError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "portfolio_not_found",
                "message": str(exc),
            },
        )

    return PortfolioResponse.from_record(portfolio)


@router.get(
    "/{portfolio_id}/activity",
    response_model=list[PortfolioActivityResponse],
    responses={404: {"model": ErrorResponse}},
)
def list_portfolio_activity(
    portfolio_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> list[PortfolioActivityResponse] | JSONResponse:
    if portfolio_id != principal.portfolio_id:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"code": "portfolio_forbidden", "message": "You cannot access this portfolio."},
        )
    service = get_portfolios_service(request)
    try:
        activity = service.list_activity(portfolio_id, limit)
    except PortfolioNotFoundError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": "portfolio_not_found", "message": str(exc)},
        )

    return [PortfolioActivityResponse.from_record(item) for item in activity]
