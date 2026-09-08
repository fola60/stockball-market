from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[3]
OPENAPI = ROOT / "packages/contracts/openapi/trading-engine.internal.v1.yaml"
SCHEMA = ROOT / "packages/contracts/schemas/trading.schema.json"
ROUTER = ROOT / "services/trading-engine/src/http/router.rs"
WORKER_CLIENT = ROOT / "services/worker/app/clients/trading_engine.py"


def _openapi_paths(document: str) -> set[str]:
    return set(re.findall(r"^  (/internal/v1/[^:]+):$", document, flags=re.MULTILINE))


def _router_paths(source: str) -> set[str]:
    return set(re.findall(r'"(/internal/v1/[^"]+)"', source))


def test_openapi_covers_every_runtime_route() -> None:
    assert _openapi_paths(OPENAPI.read_text()) == _router_paths(ROUTER.read_text())


def test_every_local_schema_reference_exists() -> None:
    openapi = OPENAPI.read_text()
    schema_defs = json.loads(SCHEMA.read_text())["$defs"]
    referenced_defs = re.findall(
        r'trading\.schema\.json#/\$defs/([A-Za-z0-9_]+)', openapi
    )
    assert referenced_defs
    assert set(referenced_defs) <= set(schema_defs)


def test_worker_client_only_calls_documented_routes() -> None:
    client_paths = set(re.findall(r'"(/internal/v1/[^"]+)"', WORKER_CLIENT.read_text()))
    assert client_paths
    assert client_paths <= _openapi_paths(OPENAPI.read_text())
