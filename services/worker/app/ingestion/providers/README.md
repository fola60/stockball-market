# Worker Ingestion Providers Module

## Purpose

Shared provider exports for external ingestion clients.

## Current Provider

FBref is the first-class provider for Premier League fixtures, players, and player stat tables.

Implementation lives in `services/worker/app/ingestion/fbref` so FBref-specific URL shapes, selectors, table IDs, comment handling, and parsing assumptions do not leak into generic ingestion services.

Provider details:

- Provider name: `FBREF`
- Base URL: `https://fbref.com`
- Premier League competition id: `9`
- Default request interval: `6.5` seconds
- Raw page cache table: `provider_raw_documents`

Supported table families:

- Scores and fixtures
- Player standard stats, used for identity and squad membership
- Player shooting, passing, defensive, and keeper stat tables when available

## Boundaries

- Provider clients should fetch data only.
- Provider clients should not contain Stockball trading rules.
- Provider clients should be used by concrete ingestion modules such as players, fixtures, stats, social, and news.
- Provider code must not bypass access controls or CAPTCHA/anti-bot systems.

## Replacement

Treat FBref as replaceable. If a licensed provider is adopted, keep the domain services and repositories on provider-neutral models and add a new provider package that emits the same ingestion records.
