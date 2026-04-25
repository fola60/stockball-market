# Worker Ingestion Providers Module

## Purpose

Future shared home for external provider clients.

## Responsibilities

- Store provider-specific HTTP clients.
- Handle API keys and authentication.
- Handle rate limits and retries.
- Normalize provider errors.
- Preserve provider IDs for reconciliation.

## Provider Candidates

### Player, Squad, Fixture Identity

Primary V1 candidate:

- `football-data.org`: structured football API with Premier League competition, teams, team squads, fixtures, and player/person IDs.

Alternatives to evaluate before implementation if cost or coverage is an issue:

- Sportmonks
- API-Football
- Fantasy Premier League public data for local/dev bootstrap only

Selection criteria:

- current Premier League squad completeness
- stable player/person IDs across seasons and clubs
- date of birth, nationality, position, team, and competition coverage
- fixture and lineup coverage for later freeze jobs
- clear terms of use for the intended product
- affordable rate limits for scheduled syncs

### Market Values

Treat market values as a distinct provider category.

Provider selection criteria:

- player-level valuation, not only squad/team aggregate value
- stable source player ID or URL
- currency and observed/update date
- clear licensing for product use
- enough identity fields to reconcile to canonical Stockball players

The provider layer should support a `manual_csv` provider so development and early seeding are not blocked while commercial valuation options are evaluated.

## Boundaries

- Provider clients should fetch data only.
- Provider clients should not contain Stockball trading rules.
- Provider clients should be used by concrete ingestion modules such as players, fixtures, stats, social, and news.
