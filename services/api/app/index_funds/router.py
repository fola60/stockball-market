from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.common.schemas import ErrorResponse
from app.index_funds.schemas import IndexFundDetailResponse, IndexFundResponse
from app.index_funds.service import IndexFundNotFoundError, IndexFundsService

router = APIRouter(prefix="/v1/index-funds", tags=["index-funds"])


def get_index_funds_service(request: Request) -> IndexFundsService:
    service = getattr(request.app.state, "index_funds_service", None)
    if service is None:
        raise RuntimeError("index funds service is not configured")
    return service


@router.get("", response_model=list[IndexFundResponse])
def list_index_funds(request: Request) -> list[IndexFundResponse]:
    funds = get_index_funds_service(request).list_index_funds()
    return [IndexFundResponse.from_record(fund) for fund in funds]


@router.get(
    "/{instrument_id}",
    response_model=IndexFundDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_index_fund(instrument_id: UUID, request: Request) -> IndexFundDetailResponse | JSONResponse:
    try:
        detail = get_index_funds_service(request).get_index_fund(instrument_id)
    except IndexFundNotFoundError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": "index_fund_not_found", "message": str(exc)},
        )
    return IndexFundDetailResponse.from_detail(detail)
