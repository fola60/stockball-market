# OpenAPI Contracts

## Purpose

Stores OpenAPI specifications for REST endpoints.

## Responsibilities

- Document public API endpoints.
- Document internal trading-engine endpoints.
- Define request and response payloads.
- Support client generation later if useful.

## Boundaries

- OpenAPI files describe HTTP contracts only.
- Database schema belongs in `infra/postgres/migrations`.
- Runtime validation belongs in each service.
