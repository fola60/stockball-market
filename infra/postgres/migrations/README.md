# PostgreSQL Migrations

## Purpose

Stores database migration files.

## Responsibilities

- Create and evolve Stockball database tables.
- Seed minimal test data where appropriate.
- Seed reusable synthetic trader strategy profiles where worker defaults need to exist in every environment.
- Preserve repeatable database setup from a clean environment.
- Store betting-market odds observations through deterministic migrations.
- Store X source registries, cursor checkpoints, injury episodes/evidence, and compact
  player availability observations through deterministic migrations.
- Normalize stable betting-market selections and player participants separately from
  append-only odds observations.
- Seed conservative and aggressive `BETTING_MARKET_VALUE` synthetic trader profiles.
- Store audited, one-off synthetic portfolio issuance and dedicated reserve ownership.
- Store manual and recurring worker execution history in the shared `job_runs` table.
- Preserve scheduled-run history while superseding stale pending snapshots and trader ticks.
- Store provider-neutral social sources, subscriptions, opaque cursors, normalized documents,
  injury observations, durable processing work, episode evidence, and rolling signal snapshots.
- Seed technically reviewed football sources for RSS, Bluesky, and Mastodon with conservative
  trust categories, retention, attribution metadata, and enabled polling subscriptions.
- Expand the Bluesky registry with every current Premier League first-team club account whose
  identity could be corroborated, while pinning immutable DIDs instead of mutable handles.
- Seed team-specific BBC, Guardian, and independent/local RSS coverage for every supported club,
  plus complementary breaking-news and transfer feeds, with explicit club-resolution hints.
- Queue policy-gated article-body enrichment for trusted RSS publishers while preserving the
  original feed summary, fetch provenance, bounded retry state, and retention controls.
- Store general player/team observations with topic and positive, negative, neutral, or mixed
  sentiment; retain injury observations as a specialized extension of that evidence.
- Audit one-off development-market valuations and enforce positive live instrument prices.
- Store high-precision price-curve state with a configurable 2.5 default full-supply multiplier,
  remove the superseded per-share increment, and audit guarded curve resets.
- Index global price-snapshot and trade timelines for incremental worker cache refreshes.
- Store password credentials, revocable opaque sessions, and auditable opening balances for
  registered users.
- Store allowlisted runtime settings and an append-only audit trail for admin changes.

## Boundaries

- Migrations define schema and controlled data changes.
- Business logic belongs in services.
- Migration files should be deterministic and reviewable.
