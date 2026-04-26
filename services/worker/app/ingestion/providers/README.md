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

Primary V1 provider:

- API-Football: structured football API with Premier League players, fixtures, per-fixture player stats, and ratings.

Alternatives to evaluate before implementation if cost or coverage is an issue:

- football-data.org
- Sportmonks
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

### Fixture And Player Stats

Use API-Football for V1 fixture and per-fixture player-stat ingestion.

Provider details:

- Base URL: `https://v3.football.api-sports.io`
- Auth header: `x-apisports-key`
- Players endpoint: `/players`
- Fixture endpoint: `/fixtures`
- Fixture player stats endpoint: `/fixtures/players`
- Premier League id: `39`

API-Football is the V1 canonical provider for players, fixtures, and player stats. That means `players.provider = https://v3.football.api-sports.io` and `players.provider_player_id` can be used to link `/fixtures/players` stat rows directly to canonical Stockball players.

## Boundaries

- Provider clients should fetch data only.
- Provider clients should not contain Stockball trading rules.
- Provider clients should be used by concrete ingestion modules such as players, fixtures, stats, social, and news.
