from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

from app.common.schemas import ErrorResponse


@dataclass(frozen=True)
class ImageRecord:
    data: bytes
    content_type: str
    content_sha256: str


IMAGE_RESPONSES: dict[int | str, dict] = {
    200: {"content": {"image/png": {}}},
    304: {"description": "The cached image is current"},
    404: {"model": ErrorResponse},
}


def image_response(
    request: Request, image: ImageRecord | None, code: str, message: str
) -> Response:
    if image is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": code, "message": message},
        )
    # Images change only when their content hash does; clients revalidate cheaply.
    headers = {"ETag": f'"{image.content_sha256}"', "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=image.data, media_type=image.content_type, headers=headers)
