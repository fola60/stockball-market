# Worker Ingestion Providers Module

## Purpose

Future shared home for external provider clients.

## Responsibilities

- Store provider-specific HTTP clients.
- Handle API keys and authentication.
- Handle rate limits and retries.
- Normalize provider errors.
- Preserve provider IDs for reconciliation.

## Boundaries

- Provider clients should fetch data only.
- Provider clients should not contain Stockball trading rules.
- Provider clients should be used by concrete ingestion modules such as players, fixtures, stats, social, and news.
