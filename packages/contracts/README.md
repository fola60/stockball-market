# Shared Contracts

## Purpose

Stores service-to-service API contracts and shared schema definitions.

## Responsibilities

- Define internal trading-engine request/response shapes.
- Define shared model schemas used by Python and Rust services.
- Keep Python and Rust services aligned on payload structure.
- Provide the source of truth for REST service communication.

## Submodules

- `openapi`: OpenAPI documents for REST APIs.
- `schemas`: shared JSON schemas and domain payload definitions.

## Boundaries

- Contains contracts only, not business logic.
- Does not own database migrations.
- Does not execute code at runtime unless later tooling is added.
- Does not include V1 derivatives, options, futures, fixtures, signals, bot strategy config, or admin APIs.

## V1 Scope

V1 uses `Instrument` as the canonical tradable concept. The only supported instrument type is `PLAYER_SHARE`.

REST and JSON Schema are the initial contract formats. gRPC, protobuf, generated clients, and package manager setup are intentionally deferred.
