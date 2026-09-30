from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse

from app.accounts.repository import AccountAlreadyExistsError
from app.auth.dependencies import bearer_token, get_auth_service, get_current_principal
from app.auth.models import CurrentPrincipal
from app.auth.schemas import AuthAccountResponse, AuthSessionResponse, LoginRequest, RegisterRequest
from app.auth.service import (
    AccountUnavailableError,
    InvalidCredentialsError,
    RegistrationUnavailableError,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/register", response_model=AuthSessionResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request) -> AuthSessionResponse | JSONResponse:
    try:
        session = get_auth_service(request).register(
            display_name=payload.display_name,
            email=payload.email,
            password=payload.password,
        )
    except AccountAlreadyExistsError as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": f"{exc.field_name}_already_exists", "message": str(exc)},
        )
    except RegistrationUnavailableError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "registration_unavailable",
                "message": "Registration is temporarily unavailable. Please try again.",
            },
        )
    return AuthSessionResponse.from_record(session)


@router.post("/login", response_model=AuthSessionResponse)
def login(payload: LoginRequest, request: Request) -> AuthSessionResponse | JSONResponse:
    try:
        session = get_auth_service(request).login(email=payload.email, password=payload.password)
    except (InvalidCredentialsError, AccountUnavailableError):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"code": "invalid_credentials", "message": "Email or password is incorrect."},
        )
    return AuthSessionResponse.from_record(session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    authorization: str | None = Header(default=None),
    _: CurrentPrincipal = Depends(get_current_principal),
) -> None:
    get_auth_service(request).logout(bearer_token(authorization))


@router.get("/me", response_model=AuthAccountResponse)
def me(
    request: Request, principal: CurrentPrincipal = Depends(get_current_principal)
) -> AuthAccountResponse:
    account = request.app.state.accounts_service.get_account(principal.account_id)
    return AuthAccountResponse.from_record(account)
