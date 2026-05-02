# Worker FBref Ingestion Provider

## Purpose

Owns FBref-specific fetching and parsing for Premier League fixtures, player identity, and player stat tables.

## Boundaries

- FBref URL patterns, table IDs, `data-stat` names, comment handling, and HTML parsing live in this package.
- Domain ingestion services consume provider-neutral `ExternalFixture`, `ExternalPlayer`, and `ExternalPlayerStat` records.
- The client uses a clear user agent, conservative throttling, transient retry/backoff, and the raw-page cache.
- The parser preserves raw parsed rows in each record's `raw_payload` or `metadata`.
- No code here executes trades, mutates prices, or bypasses access controls.

## Pages

Default Premier League pages are built from FBref competition id `9` and season start year:

- fixtures: `/en/comps/9/{season}-{season+1}/schedule/{season}-{season+1}-Premier-League-Scores-and-Fixtures`
- standard/player identity: `/en/comps/9/{season}-{season+1}/stats/{season}-{season+1}-Premier-League-Stats`
- stat tables: `shooting`, `passing`, `defense`, and `keepers` paths with the same season URL shape

## Compliance Notes

Sports Reference publishes restrictive automated access and data-use guidance:

- https://www.sports-reference.com/bot-traffic.html
- https://www.sports-reference.com/data_use.html

Keep request cadence conservative, cache pages, avoid live test traffic, and replace this provider with a licensed source if product usage requires it.
