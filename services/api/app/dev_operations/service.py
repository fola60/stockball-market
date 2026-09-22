from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

import redis

from .operations import OPERATION_DEFINITIONS, operation_definition
from .runtime_settings import RuntimeSettingsRegistry


class DevOperationsRepository(Protocol):
    def create_run(
        self,
        run_id: UUID,
        operation_type: str,
        job_type: str,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]: ...
    def mark_enqueue_failed(self, run_id: UUID, message: str) -> None: ...
    def list_runs(
        self,
        limit: int = 100,
        *,
        operation_type: str | None = None,
        exclude_operation_type: list[str] | None = None,
        status: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def get_run(self, run_id: UUID) -> dict[str, Any] | None: ...
    def summary(self) -> dict[str, Any]: ...
    def social_ingestion_summary(self) -> dict[str, Any]: ...
    def list_bots(self) -> list[dict[str, Any]]: ...
    def list_profiles(self) -> list[dict[str, Any]]: ...
    def get_bot_details(self, bot_id: UUID) -> dict[str, Any] | None: ...
    def list_trades(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        account_type: str | None = None,
        side: str | None = None,
    ) -> dict[str, Any]: ...
    def get_trade_details(self, trade_id: UUID) -> dict[str, Any] | None: ...
    def telemetry(self, hours: int) -> dict[str, Any]: ...
    def list_admin_audit_events(self, limit: int = 50) -> list[dict[str, Any]]: ...


class JobPublisher(Protocol):
    def enqueue(self, message: Mapping[str, Any]) -> None: ...


class ProcessRegistry(Protocol):
    def snapshot(self) -> dict[str, Any]: ...
    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]: ...


class RedisJobPublisher:
    def __init__(self, redis_url: str, queue_name: str) -> None:
        self._queue_name = queue_name
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def enqueue(self, message: Mapping[str, Any]) -> None:
        self._client.rpush(
            self._queue_name,
            json.dumps(dict(message), sort_keys=True, separators=(",", ":")),
        )


@dataclass(frozen=True)
class DevOperationsService:
    repository: DevOperationsRepository
    publisher: JobPublisher
    process_registry: ProcessRegistry | None = None
    runtime_settings: RuntimeSettingsRegistry | None = None

    @staticmethod
    def capabilities() -> list[dict[str, str]]:
        return [definition.capability() for definition in OPERATION_DEFINITIONS]

    def enqueue(self, operation_type: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        definition = operation_definition(operation_type)
        normalized = definition.normalize(parameters)
        run_id = uuid4()
        run = self.repository.create_run(
            run_id,
            operation_type,
            definition.job_type,
            normalized,
        )
        try:
            self.publisher.enqueue(
                {
                    "job_type": definition.job_type,
                    "payload": normalized,
                    "attempt": 0,
                    "operation_run_id": str(run_id),
                }
            )
        except Exception as error:
            self.repository.mark_enqueue_failed(run_id, f"failed to enqueue operation: {error}")
            raise
        return run

    def telemetry(self, hours: int) -> dict[str, Any]:
        result = self.repository.telemetry(hours)
        if self.process_registry is not None:
            snapshot = self.process_registry.snapshot()
            result["service_health"] = {
                "scheduler": snapshot["scheduler"],
                "queue_depth": len(snapshot["queued_jobs"]),
                "active_job": snapshot["active_job"],
            }
        return result
