# Infrastructure

## Purpose

Contains local and deployment infrastructure configuration.

## Responsibilities

- Docker Compose configuration.
- PostgreSQL migration location.
- Redis configuration location.
- Future backup, health check, and deployment scripts.

## Boundaries

- Infrastructure config should not contain application business logic.
- Service-specific code belongs under `services`.
- Shared API contracts belong under `packages/contracts`.
