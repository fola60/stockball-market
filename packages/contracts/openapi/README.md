# OpenAPI Contracts

## Purpose

Stores OpenAPI specifications for REST endpoints.

## Responsibilities

- Document internal trading-engine endpoints.
- Define request and response payloads.
- Treat OpenAPI as the source for REST service communication.
- Support client generation later if useful.

## Documents

- `trading-engine.internal.v1.yaml`: internal trading-engine API used by API and worker services.

## Boundaries

- OpenAPI files describe HTTP contracts only.
- Database schema belongs in `infra/postgres/migrations`.
- Runtime validation belongs in each service.
- V1 does not include derivatives, admin APIs, fixtures, signals, or synthetic trader strategy contracts.
