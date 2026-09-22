from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from app.auth.models import CurrentPrincipal
from app.auth.service import AccountUnavailableError, AuthService, InvalidSessionError


def get_auth_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise RuntimeError("auth service is not configured")
    return service


def bearer_token(authorization: str | None) -> str:
    scheme, separator, token = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def get_current_principal(
    request: Request, authorization: str | None = Header(default=None)
) -> CurrentPrincipal:
    token = bearer_token(authorization)
    try:
        return get_auth_service(request).authenticate(token)
    except (InvalidSessionError, AccountUnavailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
