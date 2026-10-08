# Worker Ingestion Social Module

## Purpose

Social ingestion is provider-neutral. Approved Bluesky account feeds, RSS/Atom feeds, and
selected Mastodon account timelines implement one connector contract. The legacy Twitter
injury/availability path remains available during the additive migration.

## Responsibilities

- Poll only reviewed and enabled source subscriptions.
- Normalize provider records into `SocialDocument` values.
- Atomically persist a page, enqueue new documents, and advance its opaque cursor.
- Honor RSS validators and provider rate-limit/backoff state.
- Match social observations to players, or to a reviewed source-club hint when no player resolves.
- Classify every document by topic and positive, negative, neutral, or mixed sentiment.
- Store general observations separately from specialized injury evidence.
- Preserve enough raw context for the social-sentiment strategy engine to calculate hype and sentiment.

The dependency direction is `providers -> ports <- application -> domain`. Provider response
objects never enter injury classification or trading code. One `INGEST_SOCIAL_SOURCE` job is
created per subscription, so failures and throttling are isolated.

`SocialDocumentProcessor` first writes `social_observations`. Resolved player observations feed
mention velocity and credibility-weighted sentiment snapshots; official-club posts without a
player match remain useful team observations. Only documents containing injury or recovery
evidence also write `social_injury_observations` and become eligible for episode transitions.

Trusted RSS sources may opt into article enrichment through reviewed
`metadata.article_enrichment` settings. A successful ingestion job immediately enriches and
classifies the new entries belonging to that subscription. The recurring processing job claims
up to 20 remaining article links as a recovery path. Article fetching
requires HTTPS and an exact publisher-host allowlist, follows only approved redirects, enforces a
response-size limit, and extracts the main article body. Successful extraction preserves the RSS
title/summary in `source_text`, stores the body in `enriched_text`, and classifies their combined
text. Skipped pages fall back to the RSS text; transient failures remain durably queued for three
bounded attempts. Community sources are summary-only by default.

RSS and Atom entries also keep their cleaned headline in `provider_metadata.title`, which the
public news feed displays. Entries stored before headlines were kept gain one the next time
their feed serves them; nothing else about an existing entry changes, and it is not reprocessed.

General sentiment resolution deliberately accepts a globally unique first name or surname, and
a first name or surname that is unique inside a club identified in the text. These resolutions
carry confidence `1.0`. Reviewed club aliases provide common football shorthand, including
`United` for Manchester United, `City` for Manchester City, and `Spurs` for Tottenham; a longer
club name such as `Leeds United` wins over the shorter alias. Injury episode resolution remains
limited to full names and reviewed player aliases.

## Boundaries

- Does not calculate final trading decisions.
- Does not directly mutate prices.
- Signal interpretation belongs to the synthetic trader strategy engines in `services/worker/app/synthetic_traders/engines`.
