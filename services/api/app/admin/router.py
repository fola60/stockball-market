from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.request_telemetry import known_http_routes

router = APIRouter(prefix="/internal/v1/admin", tags=["admin"])


class EnqueueOperationRequest(BaseModel):
    operation_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class SetProcessStateRequest(BaseModel):
    enabled: bool


class UpdateRuntimeSettingRequest(BaseModel):
    value: int | None
    reason: str = Field(min_length=3, max_length=500)


class UpdateEnvironmentRequest(BaseModel):
    value: str = Field(max_length=4000)
    reason: str = Field(min_length=3, max_length=500)


class OperationCapabilityResponse(BaseModel):
    operation_type: str
    job_type: str
    label: str


def _service(request: Request):
    service = getattr(request.app.state, "admin_service", None)
    if service is None:
        raise HTTPException(status_code=404, detail="admin API is disabled")
    return service


@router.post("/operations", status_code=202)
def enqueue_operation(command: EnqueueOperationRequest, request: Request) -> dict[str, Any]:
    try:
        return _service(request).enqueue(command.operation_type, command.parameters)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/operations/capabilities", response_model=list[OperationCapabilityResponse])
def list_operation_capabilities(request: Request) -> list[dict[str, str]]:
    return _service(request).capabilities()


@router.get("/runs")
def list_runs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    operation_type: str | None = Query(default=None),
    exclude_operation_type: list[str] | None = Query(default=None),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    if status not in {
        None,
        "QUEUED",
        "RUNNING",
        "RETRYING",
        "SUCCEEDED",
        "FAILED",
        "SUPERSEDED",
    }:
        raise HTTPException(status_code=422, detail="invalid run status")
    if source not in {None, "MANUAL", "SCHEDULED"}:
        raise HTTPException(status_code=422, detail="invalid run source")
    return _service(request).repository.list_runs(
        limit,
        operation_type=operation_type,
        exclude_operation_type=exclude_operation_type,
        status=status,
        source=source,
    )


@router.get("/runs/{run_id}")
def get_run(run_id: UUID, request: Request) -> dict[str, Any]:
    run = _service(request).repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/summary")
def get_summary(request: Request) -> dict[str, Any]:
    return _service(request).repository.summary()


@router.get("/social-ingestion")
def get_social_ingestion_summary(request: Request) -> dict[str, Any]:
    return _service(request).repository.social_ingestion_summary()


@router.get("/telemetry")
def get_telemetry(
    request: Request, hours: int = Query(default=24, ge=1, le=168)
) -> dict[str, Any]:
    result = _service(request).telemetry(hours)
    request_telemetry = request.app.state.request_telemetry
    result["endpoint_metrics"] = request_telemetry.snapshot(
        hours, known_http_routes(request.app)
    )
    return result


@router.get("/runtime-settings")
def list_runtime_settings(request: Request) -> list[dict[str, Any]]:
    registry = _service(request).runtime_settings
    if registry is None:
        raise HTTPException(status_code=404, detail="runtime settings are unavailable")
    return registry.list()


@router.patch("/runtime-settings/{setting_key}")
def update_runtime_setting(
    setting_key: str, command: UpdateRuntimeSettingRequest, request: Request
) -> dict[str, Any]:
    registry = _service(request).runtime_settings
    if registry is None:
        raise HTTPException(status_code=404, detail="runtime settings are unavailable")
    actor = request.headers.get("x-admin-actor", "admin-ui")[:100]
    try:
        return registry.update(
            setting_key, command.value, actor=actor, reason=command.reason
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/audit-events")
def list_audit_events(
    request: Request, limit: int = Query(default=50, ge=1, le=200)
) -> list[dict[str, Any]]:
    return _service(request).repository.list_admin_audit_events(limit)


@router.get("/environment")
def list_environment(request: Request) -> list[dict[str, Any]]:
    service = getattr(request.app.state, "environment_service", None)
    if service is None:
        raise HTTPException(status_code=404, detail="environment editing is unavailable")
    return service.list()


@router.patch("/environment/{name}")
def update_environment(
    name: str, command: UpdateEnvironmentRequest, request: Request
) -> dict[str, Any]:
    service = getattr(request.app.state, "environment_service", None)
    if service is None:
        raise HTTPException(status_code=404, detail="environment editing is unavailable")
    actor = request.headers.get("x-admin-actor", "admin-ui")[:100]
    try:
        return service.update(name, command.value, actor=actor, reason=command.reason)
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/processes")
def list_processes(request: Request) -> dict[str, Any]:
    registry = _service(request).process_registry
    if registry is None:
        raise HTTPException(status_code=404, detail="process controls are unavailable")
    return registry.snapshot()


@router.patch("/processes/{process_name}")
def set_process_state(
    process_name: str, command: SetProcessStateRequest, request: Request
) -> dict[str, Any]:
    registry = _service(request).process_registry
    if registry is None:
        raise HTTPException(status_code=404, detail="process controls are unavailable")
    try:
        return registry.set_enabled(process_name, command.enabled)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/synthetic-traders")
def list_synthetic_traders(request: Request) -> list[dict[str, Any]]:
    return _service(request).repository.list_bots()


@router.get("/synthetic-traders/{bot_id}")
def get_synthetic_trader(bot_id: UUID, request: Request) -> dict[str, Any]:
    bot = _service(request).repository.get_bot_details(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="synthetic trader not found")
    return bot


@router.get("/synthetic-trader-profiles")
def list_synthetic_trader_profiles(request: Request) -> list[dict[str, Any]]:
    return _service(request).repository.list_profiles()


@router.get("/trades")
def list_trades(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    account_type: str | None = Query(default=None),
    side: str | None = Query(default=None),
) -> dict[str, Any]:
    if account_type not in {None, "USER", "ADMIN", "SYNTHETIC_TRADER"}:
        raise HTTPException(status_code=422, detail="invalid account type")
    if side not in {None, "BUY", "SELL"}:
        raise HTTPException(status_code=422, detail="invalid trade side")
    return _service(request).repository.list_trades(
        limit=limit,
        offset=offset,
        account_type=account_type,
        side=side,
    )


@router.get("/trades/{trade_id}")
def get_trade_details(trade_id: UUID, request: Request) -> dict[str, Any]:
    trade = _service(request).repository.get_trade_details(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="trade not found")
    return trade
