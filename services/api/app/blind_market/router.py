from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.accounts.models import AccountType
from app.auth.dependencies import get_current_principal
from app.auth.models import CurrentPrincipal
from app.blind_market.service import BlindMarketService, Call, RoundClosedError
from app.clients.trading_engine import TradingEngineClientError, TradingEngineUnavailableError

router = APIRouter(prefix="/v1/blind-market", tags=["blind-market"])


def get_service(request: Request) -> BlindMarketService:
    service = request.app.state.blind_market_service
    if service is None:
        raise HTTPException(503, "Daily Games is temporarily unavailable.")
    return service


def human_player(principal: CurrentPrincipal = Depends(get_current_principal)) -> CurrentPrincipal:
    if principal.account_type != AccountType.USER:
        raise HTTPException(403, "Daily Games entries require a player account.")
    return principal


@router.get("")
def get_round(
    request: Request, response: Response, day: date | None = None,
    authorization: str | None = Header(default=None),
    service: BlindMarketService = Depends(get_service),
) -> dict[str, Any]:
    principal = None
    if authorization:
        try:
            principal = get_current_principal(request, authorization)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
    response.headers["Cache-Control"] = "private, no-store"
    return service.round_view(day, principal.account_id if principal else None)


@router.post("/entries")
def call_player(
    call: Call,
    principal: CurrentPrincipal = Depends(human_player),
    service: BlindMarketService = Depends(get_service),
) -> dict[str, Any]:
    try:
        return service.call(principal.account_id, call)
    except RoundClosedError as exc:
        raise HTTPException(409, "This game has closed. Open today’s game to play.") from exc


@router.post("/claim", status_code=204)
def claim_reward(
    principal: CurrentPrincipal = Depends(human_player),
    service: BlindMarketService = Depends(get_service),
) -> Response:
    try:
        service.claim(principal)
    except (TradingEngineClientError, TradingEngineUnavailableError) as exc:
        raise HTTPException(503, "Your reward is saved. Try claiming it again shortly.") from exc
    return Response(status_code=204)
