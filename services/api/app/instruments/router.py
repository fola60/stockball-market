from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.common.schemas import ErrorResponse
from app.instruments.models import ImageRecord
from app.instruments.schemas import InstrumentResponse, PlayerStatsResponse, PriceSnapshotResponse
from app.instruments.service import InstrumentNotFoundError, InstrumentsService

router = APIRouter(prefix="/v1/instruments", tags=["instruments"])


def get_instruments_service(request: Request) -> InstrumentsService:
    service = getattr(request.app.state, "instruments_service", None)
    if service is None:
        raise RuntimeError("instruments service is not configured")
    return service


@router.get("", response_model=list[InstrumentResponse])
def list_instruments(request: Request) -> list[InstrumentResponse]:
    service = get_instruments_service(request)
    instruments = service.list_instruments()
    return [InstrumentResponse.from_record(instrument) for instrument in instruments]


@router.get(
    "/{instrument_id}",
    response_model=InstrumentResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_instrument(
    instrument_id: UUID, request: Request
) -> InstrumentResponse | JSONResponse:
    service = get_instruments_service(request)
    try:
        instrument = service.get_instrument(instrument_id)
    except InstrumentNotFoundError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "instrument_not_found",
                "message": str(exc),
            },
        )

    return InstrumentResponse.from_record(instrument)


@router.get(
    "/{instrument_id}/price-history",
    response_model=list[PriceSnapshotResponse],
    responses={404: {"model": ErrorResponse}},
)
def list_price_history(
    instrument_id: UUID,
    request: Request,
    range: Literal["1D", "1W", "1M", "3M", "1Y", "ALL"] = "ALL",
) -> list[PriceSnapshotResponse] | JSONResponse:
    service = get_instruments_service(request)
    try:
        history = service.list_price_history(instrument_id, range)
    except InstrumentNotFoundError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "instrument_not_found",
                "message": str(exc),
            },
        )

    return [PriceSnapshotResponse.from_record(snapshot) for snapshot in history]


@router.get(
    "/{instrument_id}/player-stats",
    response_model=PlayerStatsResponse | None,
    responses={404: {"model": ErrorResponse}},
)
def get_player_stats(
    instrument_id: UUID, request: Request
) -> PlayerStatsResponse | None | JSONResponse:
    service = get_instruments_service(request)
    try:
        stats_record = service.get_player_stats(instrument_id)
    except InstrumentNotFoundError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "instrument_not_found",
                "message": str(exc),
            },
        )

    if stats_record is None:
        return None
    return PlayerStatsResponse.from_record(stats_record)


_IMAGE_RESPONSES: dict[int | str, dict] = {
    200: {"content": {"image/png": {}}},
    304: {"description": "The cached image is current"},
    404: {"model": ErrorResponse},
}


@router.get(
    "/{instrument_id}/player-image",
    response_class=Response,
    responses=_IMAGE_RESPONSES,
)
def get_player_image(instrument_id: UUID, request: Request) -> Response:
    image = get_instruments_service(request).get_player_image(instrument_id)
    return _image_response(request, image, "player_image_not_found", "player image")


@router.get(
    "/{instrument_id}/club-badge",
    response_class=Response,
    responses=_IMAGE_RESPONSES,
)
def get_club_badge(instrument_id: UUID, request: Request) -> Response:
    image = get_instruments_service(request).get_club_badge(instrument_id)
    return _image_response(request, image, "club_badge_not_found", "club badge")


def _image_response(
    request: Request, image: ImageRecord | None, code: str, label: str
) -> Response:
    if image is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": code, "message": f"no {label} is available for this instrument"},
        )
    # Images change only when their content hash does; clients revalidate cheaply.
    headers = {"ETag": f'"{image.content_sha256}"', "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=image.data, media_type=image.content_type, headers=headers)
