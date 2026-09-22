from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic, time
from typing import Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


@dataclass(frozen=True)
class RequestSample:
    observed_at: float
    duration_ms: float
    status_code: int


class RequestTelemetry:
    def __init__(self, max_samples_per_endpoint: int = 50_000) -> None:
        self._samples: dict[tuple[str, str], Deque[RequestSample]] = defaultdict(
            lambda: deque(maxlen=max_samples_per_endpoint)
        )
        self._lock = threading.Lock()

    def observe(self, method: str, route: str, duration_ms: float, status_code: int) -> None:
        with self._lock:
            self._samples[(method, route)].append(
                RequestSample(time(), duration_ms, status_code)
            )

    def snapshot(self, hours: int, known_routes: set[tuple[str, str]]) -> list[dict[str, object]]:
        cutoff = time() - hours * 60 * 60
        with self._lock:
            samples = {
                key: [sample for sample in values if sample.observed_at >= cutoff]
                for key, values in self._samples.items()
            }
        rows: list[dict[str, object]] = []
        for method, route in sorted(known_routes | set(samples)):
            values = samples.get((method, route), [])
            durations = sorted(sample.duration_ms for sample in values)
            errors = sum(sample.status_code >= 400 for sample in values)
            count = len(values)
            rows.append(
                {
                    "method": method,
                    "route": route,
                    "request_count": count,
                    "error_count": errors,
                    "error_rate": round(errors * 100 / count, 2) if count else 0.0,
                    "requests_per_minute": round(count / (hours * 60), 2),
                    "min_ms": round(durations[0], 2) if durations else None,
                    "average_ms": round(sum(durations) / count, 2) if durations else None,
                    "p50_ms": _percentile(durations, 50),
                    "p90_ms": _percentile(durations, 90),
                    "p95_ms": _percentile(durations, 95),
                    "p99_ms": _percentile(durations, 99),
                    "max_ms": round(durations[-1], 2) if durations else None,
                    "last_seen_at": (
                        datetime.fromtimestamp(values[-1].observed_at, UTC).isoformat()
                        if values
                        else None
                    ),
                }
            )
        return rows


class RequestTelemetryMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, telemetry: RequestTelemetry) -> None:
        super().__init__(app)
        self._telemetry = telemetry

    async def dispatch(self, request: Request, call_next):
        started = monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route_object = request.scope.get("route")
            route = getattr(route_object, "path", None) or request.url.path
            self._telemetry.observe(
                request.method,
                route,
                (monotonic() - started) * 1000,
                status_code,
            )


def known_http_routes(app) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    openapi = getattr(app, "openapi", None)
    if callable(openapi):
        for path, operations in openapi().get("paths", {}).items():
            for method in operations:
                if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    routes.add((method.upper(), path))
    for route in app.routes:
        path = getattr(route, "path", None)
        for method in getattr(route, "methods", set()):
            if path and method not in {"HEAD", "OPTIONS"}:
                routes.add((method, path))
    return routes


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    rank = max(0, math.ceil(percentile / 100 * len(values)) - 1)
    return round(values[rank], 2)
