# Free Social Ingestion Implementation Plan

## Status

This document is an implementation plan. It does not represent completed work.

## Goal

Build a free-to-access, provider-neutral social ingestion system for player injury,
availability, sentiment, and attention signals. The first supported sources will be:

1. Bluesky public account feeds.
2. Allowlisted RSS and Atom feeds.
3. Mastodon public account feeds on selected instances.

The design must make adding or removing a provider an adapter-level change. Provider
clients must not own player resolution, injury classification, episode management, or
trading decisions.

"Free" means that the provider does not charge an API access fee. Infrastructure,
network, moderation, source review, and compliance costs still apply.

## Eligibility Assessment

| Source | Authentication | Access and limits | Coverage considerations | Decision |
| --- | --- | --- | --- | --- |
| Bluesky AppView | Most public reads require no token | Public `app.bsky.*` GET endpoints are available through `public.api.bsky.app`; clients must handle throttling dynamically | Coverage must be validated against a seed list of football clubs, leagues, players, and journalists | MVP |
| Bluesky Jetstream | No user session is required for the public stream | Filterable event stream with replay cursors; the hosted service is described as free but rate-limited and evolving | Best used with approved account DIDs rather than ingesting the entire network | Phase 2 |
| RSS/Atom | Normally none | Publisher-specific terms; conditional HTTP requests substantially reduce traffic | Strong fit for official club, league, journalist, and sports-news feeds | MVP |
| Mastodon | Public reads may need no token; search and streaming capabilities can require one | Default server limit is 300 requests per five minutes per account and per IP, but each instance can alter it | Data is instance-scoped and full-text search availability varies | Phase 3 |

Eligibility references:

- [Bluesky HTTP API reference](https://docs.bsky.app/docs/api/app-bsky-feed-get-feed)
  documents unauthenticated public reads, author feeds, and post search.
- [Bluesky Jetstream documentation](https://github.com/bluesky-social/jetstream/blob/main/docs/README.md)
  describes collection and DID filtering, replay cursors, and the hosted service's
  free, rate-limited status.
- [Mastodon search documentation](https://docs.joinmastodon.org/methods/search/)
  explains that status search depends on authentication and instance search support.
- [Mastodon rate-limit documentation](https://docs.joinmastodon.org/api/rate-limits/)
  documents the default limits and response headers.
- [HTTP conditional-request semantics](https://datatracker.ietf.org/doc/html/rfc9110)
  define `ETag`, `If-None-Match`, `Last-Modified`, and `If-Modified-Since` handling for
  efficient feed polling.

Before enabling any source, record its terms-review date, allowed retention model,
attribution requirements, and whether complete post text may be stored. RSS eligibility
is assessed per publisher because there is no single licence covering every feed.

## Source Selection Policy

Only approved sources may produce evidence that changes an injury or availability
episode. Broad search may identify source candidates, but its results must not become
trusted evidence automatically.

Source categories and initial trust policy:

| Category | Example | Initial evidence policy |
| --- | --- | --- |
| `OFFICIAL_LEAGUE` | League or competition account/feed | May create or update an episode |
| `OFFICIAL_CLUB` | Club account/feed | May create or update an episode |
| `PLAYER` | Verified player-controlled account/feed | May create or update an episode after identity review |
| `JOURNALIST` | Approved reporter | Requires confidence threshold or corroboration |
| `NEWS_ORGANISATION` | Approved sports publisher | Requires confidence threshold or corroboration |
| `COMMUNITY` | Unofficial account or feed | Discovery and aggregate sentiment only |

Every source record will contain an enabled flag, trust weight, source category,
approval actor and timestamp, policy status, retention period, and stable provider
identifier. Account handles are display attributes rather than identities; Bluesky DIDs
and Mastodon instance-qualified account IDs are the stable identifiers.

## Target Architecture

```text
services/worker/app/ingestion/social/
├── domain/
│   ├── documents.py          # Normalized documents and provider identifiers
│   ├── sources.py            # Sources, subscriptions, trust and policy state
│   ├── cursors.py            # Opaque cursors and rate-limit state
│   └── errors.py             # Provider-neutral error types
├── application/
│   ├── ingest.py             # Poll, normalize, persist and enqueue processing
│   ├── process.py            # Resolve, classify and update evidence
│   └── source_registry.py    # Source approval and connector lookup
├── ports/
│   ├── connector.py          # Provider connector protocol
│   └── repository.py         # Persistence protocol
├── providers/
│   ├── bluesky/
│   │   ├── client.py
│   │   ├── connector.py
│   │   └── mapper.py
│   ├── rss/
│   │   ├── client.py
│   │   ├── connector.py
│   │   └── parser.py
│   └── mastodon/
│       ├── client.py
│       ├── connector.py
│       └── mapper.py
├── injuries/
│   ├── classifier.py
│   ├── episodes.py
│   └── resolution.py
└── repository/
    └── postgres.py
```

The folders express the dependency direction:

```text
provider adapters -> ports <- application services -> domain
                              |
                              v
                        PostgreSQL repository
```

Domain and application modules must not import provider packages. This keeps the core
testable with in-memory connectors and prevents provider response formats from leaking
into classification or trading logic.

## Core Contracts

Use one normalized document type for posts and feed entries:

```python
@dataclass(frozen=True)
class SocialDocument:
    provider: SocialProvider
    external_id: str
    source_id: UUID
    document_kind: SocialDocumentKind
    author_external_id: str | None
    text: str
    published_at: datetime
    canonical_url: str
    language: str | None
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class PollResult:
    documents: Sequence[SocialDocument]
    next_cursor: Mapping[str, object] | None
    retry_after: timedelta | None
    rate_limit: RateLimitState | None


class SocialConnector(Protocol):
    provider: SocialProvider

    async def poll(
        self,
        subscription: SocialSubscription,
        cursor: IngestionCursor | None,
    ) -> PollResult:
        ...
```

The cursor is opaque JSON owned by the adapter. It can hold a Bluesky cursor, a
Jetstream event timestamp, Mastodon pagination IDs, or RSS validators without changing
the orchestration service.

Standard connector errors will be:

- `RateLimited`, including a retry time where available.
- `TransientProviderError`, eligible for bounded retry.
- `InvalidSubscription`, requiring source configuration repair.
- `PolicyDisabled`, indicating that eligibility has expired or been revoked.
- `PermanentProviderError`, requiring operator review.

## Provider Plans

### Bluesky polling MVP

1. Maintain an approved list of Bluesky DIDs.
2. Resolve handles to DIDs only during source setup or identity refresh.
3. Poll `app.bsky.feed.getAuthorFeed` for each approved DID.
4. Normalize original posts and quoted-post context; ignore repost-only events unless
   engagement analytics explicitly needs them.
5. Persist the returned cursor only after the documents commit successfully.
6. Treat general post search as a discovery tool whose sources require manual approval.
7. Read rate-limit responses and back off dynamically rather than coding an assumed
   numeric quota.

### RSS/Atom MVP

1. Accept only explicitly approved feed URLs.
2. Reject redirects to unapproved hosts unless an operator accepts the new target.
3. Parse RSS 2.0 and Atom into the same `SocialDocument` contract.
4. Prefer entry GUIDs as external IDs; otherwise use a canonical URL and content hash.
5. Persist `ETag` and `Last-Modified` and issue conditional requests on later polls.
6. Apply response-size, item-count, redirect, and timeout limits.
7. Sanitize HTML to normalized text before classification.
8. Record publisher-specific attribution and retention rules on the source.

### Bluesky Jetstream phase 2

1. Subscribe only to required collections, initially `app.bsky.feed.post`.
2. Filter events to approved DIDs before normalization.
3. Persist replay cursors frequently and reconnect with exponential backoff and jitter.
4. Handle create, update, and delete events explicitly.
5. Deduplicate replayed events using the document uniqueness constraint.
6. Retain polling as a recovery path until stream reliability has been demonstrated.

### Mastodon phase 3

1. Store the instance base URL and stable account ID for each source.
2. Poll approved account timelines rather than depending on global search.
3. Maintain rate-limit and backoff state per instance.
4. Prevent one unavailable instance from delaying other instances or providers.
5. Introduce an application token only where an instance requires it, and store secrets
   outside subscription JSON.
6. Add server capability discovery because versions and enabled features differ.

## Persistence Plan

Add a new migration with provider-neutral tables:

### `social_sources`

- `id`
- `provider`
- `external_source_id`
- `display_handle`
- `canonical_url`
- `source_category`
- `trust_weight`
- `enabled`
- `policy_status`
- `terms_reviewed_at`
- `retention_days`
- `approved_by`
- `approved_at`
- `metadata JSONB`
- unique `(provider, external_source_id)`

### `social_subscriptions`

- `id`
- `source_id`
- `provider`
- `mode` such as `AUTHOR_FEED`, `RSS_FEED`, or `STREAM`
- non-secret `configuration JSONB`
- polling interval
- enabled and scheduling state

### `social_ingestion_cursors`

- `subscription_id`
- opaque `cursor JSONB`
- `etag`
- `last_modified`
- last poll and success timestamps
- consecutive failure count
- next eligible poll time
- rate-limit metadata

### `social_documents`

- provider and external ID
- source and subscription IDs
- document kind
- author identifier
- publication and ingestion timestamps
- canonical URL and language
- normalized text or permitted excerpt
- content hash
- provider metadata
- deletion timestamp
- unique `(provider, external_id)`

### `social_injury_observations`

- document ID
- classifier version
- player-resolution result and confidence
- injury classification and confidence
- extracted availability window
- evidence status
- timestamps

### `player_social_signal_snapshots`

- player and calculation timestamp
- lookback window
- trusted mention count
- credibility-weighted sentiment
- injury-confirmation count
- mention velocity
- corroborating source count
- signal confidence and age

Schema rollout will be additive:

1. Create the generic tables and constraints.
2. Backfill reusable existing sources, documents, aliases, and observations.
3. Compare old and new episode-processing results using a fixed fixture corpus.
4. Switch reads and writes behind a feature flag.
5. Observe at least one complete retention window.
6. Remove compatibility paths in a separate migration after rollback is no longer
   required.

## Job and Scheduling Design

Use a generic `INGEST_SOCIAL_SOURCE` job with a subscription ID. Scheduling one job per
subscription provides isolation, independent backoff, and small retry units.

The handler will:

1. Load the subscription and confirm its policy eligibility.
2. Resolve its connector from a provider registry.
3. Load its cursor.
4. Poll and normalize a bounded page.
5. Atomically persist documents, enqueue processing, and advance the cursor.
6. Record rate-limit state and schedule the next poll.

Classification and player resolution should run as separate idempotent work. Slow model
calls or ambiguous player resolution will therefore not hold provider cursors open.

## Signal and Trading Boundary

Raw ingestion must not make trading decisions. It will produce normalized documents and
injury observations. A separate aggregation job will calculate rolling social features
and write `player_social_signal_snapshots`.

Synthetic traders will read only the latest non-expired snapshot. Social features must
initially be protected by a strategy feature flag and evaluated in backtests before
affecting live bot orders.

Suggested initial features:

- Mentions from trusted sources over 15-minute, 1-hour, and 24-hour windows.
- Credibility-weighted sentiment.
- Confirmed injury or availability reports.
- Mention velocity compared with the player's baseline.
- Number and category of corroborating sources.
- Age, confidence, and completeness of the aggregate.

## Reliability, Performance, and Observability

### Reliability

- Advance cursors only in the same transaction that durably records the page.
- Make document and observation writes idempotent.
- Retry transient failures with capped exponential backoff and jitter.
- Respect `Retry-After` and provider rate-limit headers.
- Apply per-provider and per-instance concurrency limits.
- Use circuit breakers so repeated failures do not create retry storms.
- Bound response sizes, pages, parsing time, and processing batches.
- Represent deletions with tombstones and propagate them to derived evidence.

### Performance

- Use RSS conditional requests to avoid downloading unchanged feeds.
- Filter Jetstream by collection and approved DID before downstream processing.
- Batch database inserts while preserving per-page transaction boundaries.
- Calculate rolling signals asynchronously rather than during document ingestion.
- Index document uniqueness, source publication time, unresolved observations, and
  snapshot lookup keys.
- Keep raw provider metadata out of frequently scanned aggregate queries.

### Metrics

- `social_poll_duration_seconds{provider}`
- `social_documents_fetched_total{provider}`
- `social_documents_new_total{provider}`
- `social_documents_duplicate_total{provider}`
- `social_processing_duration_seconds{stage}`
- `social_cursor_lag_seconds{provider}`
- `social_rate_limited_total{provider}`
- `social_provider_errors_total{provider,error_type}`
- `social_observations_unresolved`
- `social_episode_updates_total{classification}`
- `social_deletions_total{provider}`

Do not use handles, subscription IDs, player IDs, document IDs, or URLs as metric labels.
Put those identifiers in structured logs with a run ID and trace ID instead.

## Privacy and Retention Gate

Player injury and availability information can constitute health-related personal data.
Public availability alone does not establish that the player personally made the data
public. The production design therefore requires a documented privacy assessment and
legal review before enabling injury evidence. The
[GDPR definition and recitals](https://eur-lex.europa.eu/eli/reg/2016/679/art_4/par_1/oj)
describe health data broadly.

Required controls:

- Document the lawful basis and applicable special-category condition.
- Collect only public content from approved sources.
- Store the minimum text necessary for classification and audit.
- Apply provider- and publisher-specific retention periods.
- Support source revocation, document deletion, and derived-evidence invalidation.
- Restrict raw content access and record administrative changes.
- Never ingest private, followers-only, or access-controlled personal content.

## Implementation Sequence

### PR 1: Characterization and neutral contracts

- Add fixture-based tests for current player resolution, injury classification, and
  episode transitions.
- Add provider-neutral domain models, connector protocol, repository protocol, and
  typed errors.
- Extract reusable injury processing into the `injuries` package without changing its
  outcomes.

### PR 2: Generic persistence and scheduling

- Add provider-neutral tables and repository methods.
- Add the source/subscription registry and policy gate.
- Add one-subscription-per-job scheduling, transactional cursor advancement, metrics,
  and structured logs.
- Backfill reusable historical records and verify parity.

### PR 3: Bluesky polling

- Implement handle-to-DID source setup and approved-DID author-feed polling.
- Add response fixtures, pagination, replay, deletion, throttling, and idempotency tests.
- Seed a small reviewed football source list and measure coverage for two weeks.

### PR 4: RSS and Atom

- Implement safe feed fetching, parsing, canonicalization, conditional requests, and
  HTML sanitization.
- Add publisher policy metadata and feed-health administration.
- Seed official club, league, and approved publisher feeds.

### PR 5: Signal aggregation

- Build rolling player-level signal snapshots.
- Read snapshots through the synthetic-trader repository.
- Add freshness checks, feature flags, backtest fixtures, and comparison reporting.

### PR 6: Jetstream

- Add filtered streaming, durable replay cursors, reconnect logic, and tombstones.
- Compare stream completeness and latency with polling before making it primary.

### PR 7: Mastodon

- Add instance capability discovery and approved-account polling.
- Add per-instance throttling and failure isolation.
- Enable only instances whose source coverage justifies the operational cost.

### PR 8: Cleanup and operational documentation

- Remove obsolete provider-specific persistence and compatibility paths.
- Split repository modules that have accumulated unrelated queries.
- Document source approval, incident response, retention, replay, and provider-adapter
  development.

## Testing Strategy

Every connector must pass a shared contract suite covering:

- Empty and multi-page responses.
- Duplicate pages and cursor replay.
- Invalid and expired cursors.
- Rate limits and server errors.
- Timeouts and malformed records.
- Edited and deleted documents.
- Crash before commit and crash after commit.
- Provider metadata that contains missing or unexpected fields.

Additional test layers:

- Provider fixture tests with sanitized recorded responses.
- Repository integration tests against PostgreSQL.
- End-to-end ingestion tests using fake connectors.
- Classification parity tests against the characterization corpus.
- Load tests for polling, persistence, classification queues, and snapshot aggregation.
- Backtests proving that enabling social features does not create unbounded bot activity.

Live-provider tests should be opt-in and must not be required for the deterministic CI
suite.

## Definition of Done

- Bluesky and RSS ingestion run without paid provider credentials.
- All providers implement the same connector contract and shared tests.
- No provider types or response fields leak into injury or trading modules.
- Replaying a page creates no duplicate documents or observations.
- A cursor cannot advance after a partial persistence failure.
- One provider or Mastodon instance failing does not block another.
- Only reviewed, enabled sources can change injury episodes.
- Search-discovered and community content cannot silently become trusted evidence.
- Retention, deletion, and source-revocation rules are enforced in stored and derived
  data.
- Social-signal snapshots include confidence and freshness and are read behind a feature
  flag.
- Metrics expose provider latency, lag, throttling, processing cost, and failure rate
  without high-cardinality labels.
- Architecture, source approval, operations, and adapter-development documentation are
  complete.

## Decisions to Confirm Before Implementation

1. Whether injury evidence may retain full public text, a short excerpt, or only a hash,
   canonical URL, and extracted facts.
2. Which clubs, leagues, journalists, and publishers form the initial approved source
   set.
3. The corroboration threshold for journalist and news-organisation reports.
4. Polling freshness targets and the maximum daily infrastructure budget.
5. Whether the initial release includes injury intelligence only or also general
   sentiment and mention-volume signals.
