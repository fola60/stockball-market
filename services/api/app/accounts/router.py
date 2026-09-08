from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from app.accounts.models import AccountType, CreateAccountCommand
from app.accounts.repository import AccountAlreadyExistsError
from app.accounts.schemas import AccountResponse, CreateAccountRequest
from app.accounts.service import AccountNotFoundError, AccountsService
from app.common.schemas import ErrorResponse

router = APIRouter()
public_router = APIRouter(prefix="/v1/accounts", tags=["accounts"])
internal_router = APIRouter(prefix="/internal/v1/accounts", tags=["internal-accounts"])


def get_accounts_service(request: Request) -> AccountsService:
    return request.app.state.accounts_service


@public_router.post(
    "/users",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
def create_user(payload: CreateAccountRequest, request: Request) -> AccountResponse | JSONResponse:
    return _create_account(payload, request, AccountType.USER)


@public_router.post(
    "/admins",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
def create_admin(
    payload: CreateAccountRequest, request: Request
) -> AccountResponse | JSONResponse:
    return _create_account(payload, request, AccountType.ADMIN)


@internal_router.post(
    "/synthetic-traders",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
def create_synthetic_trader(
    payload: CreateAccountRequest, request: Request
) -> AccountResponse | JSONResponse:
    return _create_account(payload, request, AccountType.SYNTHETIC_TRADER)


def _create_account(
    payload: CreateAccountRequest,
    request: Request,
    account_type: AccountType,
) -> AccountResponse | JSONResponse:
    service = get_accounts_service(request)
    try:
        account = service.create_account(
            CreateAccountCommand(
                handle=payload.handle,
                display_name=payload.display_name,
                email=str(payload.email) if payload.email is not None else None,
                account_type=account_type,
            )
        )
    except AccountAlreadyExistsError as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": f"{exc.field_name}_already_exists",
                "message": str(exc),
            },
        )

    return AccountResponse.from_record(account)


@public_router.get("", response_model=list[AccountResponse])
def list_accounts(
    request: Request,
    account_type: AccountType | None = Query(default=None),
) -> list[AccountResponse]:
    service = get_accounts_service(request)
    accounts = service.list_accounts(account_type)
    return [AccountResponse.from_record(account) for account in accounts]


@public_router.get(
    "/{account_id}",
    response_model=AccountResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_account(account_id: UUID, request: Request) -> AccountResponse | JSONResponse:
    service = get_accounts_service(request)
    try:
        account = service.get_account(account_id)
    except AccountNotFoundError as exc:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "account_not_found",
                "message": str(exc),
            },
        )

    return AccountResponse.from_record(account)


router.include_router(public_router)
router.include_router(internal_router)
