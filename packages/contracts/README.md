# Shared Contracts

## Purpose

Stores service-to-service API contracts and shared schema definitions.

## Responsibilities

- Define internal trading-engine request/response shapes.
- Define public API schemas where useful.
- Keep Python and Rust services aligned on payload structure.
- Provide the source of truth for generated or manually implemented clients.

## Submodules

- `openapi`: OpenAPI documents for REST APIs.
- `schemas`: shared JSON schemas and domain payload definitions.

## Boundaries

- Contains contracts only, not business logic.
- Does not own database migrations.
- Does not execute code at runtime unless later tooling is added.
