from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.common.schemas import ErrorResponse
from app.portfolios.schemas import PortfolioResponse
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
    portfolio_id: UUID, request: Request
) -> PortfolioResponse | JSONResponse:
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
