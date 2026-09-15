# Social ingestion operations

## Source approval

No connector performs broad discovery during ingestion. Add a `social_sources` row only after
reviewing identity, publisher terms, retention, attribution, and the privacy basis for injury
evidence. Bluesky identities use DIDs; Mastodon identities use the instance-qualified account ID;
RSS identities use an operator-assigned publisher/feed key. Handles are display data.

Set `policy_status=APPROVED` before `enabled=true`. Community sources remain aggregate-only. A
journalist or news source must meet the classifier confidence threshold before it can affect an
episode. Never put tokens, passwords, or authorization headers in subscription configuration.

Provider configuration:

- Bluesky `AUTHOR_FEED`: `{"did": "did:plc:..."}`. Resolve handles only during reviewed setup.
- RSS `RSS_FEED`: `{"url": "https://...", "approved_redirect_hosts": ["..."]}`.
- Mastodon `AUTHOR_FEED`: `{"instance_url": "https://...", "account_id": "..."}`.

Migration `0017_social_source_seeds.sql` supplies the initial enabled set: BBC Sport Football,
The Guardian Football, and Le Monde Football RSS; the official Everton, Newcastle United,
Manchester City, and Tottenham Hotspur Bluesky accounts; and Footiebuzz on Mastodon. The
Mastodon source is deliberately `COMMUNITY`, so it can contribute only aggregate sentiment and
attention. Applying the migration makes every subscription immediately eligible for polling.

Migration `0019_expand_official_bluesky_sources.sql` adds the corroborated Brentford, Brighton &
Hove Albion, Fulham, Sunderland, and Crystal Palace first-team accounts. Together the two
migrations cover nine current Premier League clubs. The September 2026 audit did not approve
plausible-looking Arsenal, Aston Villa, Bournemouth, Chelsea, Coventry City, Hull City, Ipswich
Town, Leeds United, Liverpool, Manchester United, or Nottingham Forest profiles: they were
unverified, explicitly unofficial, empty/unowned, suspended, deactivated, or lacked independent
identity evidence. Recheck them in a later source review rather than guessing ownership.

Migration `0020_team_specific_rss_sources.sql` adds a BBC feed for every supported club, a
Guardian feed for every supported club except Brighton (whose team endpoint currently returns
404), and one active independent or local feed per club. It also adds Sky Sports Football, ESPN
Soccer, and The Guardian's transfer-window feed. Every team feed records `metadata.club`, giving
the entity resolver a deterministic club hint even when an article uses only a player's first or
last name. Community publishers remain low-trust and aggregate-only. The older broad BBC and
Guardian subscriptions are disabled because their article GUIDs overlap the team feeds and could
otherwise cause documents to be stored before the club hint is available.

Migration `0021_social_article_enrichment.sql` adds durable article-body enrichment for the
approved BBC, Guardian, Sky Sports, ESPN, Le Monde, Argus, Coventry Telegraph, and Hull Daily Mail
hosts. The original RSS title/summary and extracted article body are retained separately. Article
requests require HTTPS, remain on an explicit source-level host allowlist, allow at most three
redirects, accept HTML only, and are capped at 1.5 MB. Newly inserted entries are enriched and
classified inside their source-ingestion job after database deduplication. The recurring processing
job drains interrupted and historical work in batches of 20. Temporary failures receive three
bounded attempts, while blocked, non-HTML, oversized, or unextractable pages become `SKIPPED` and
continue through classification using their RSS text.

The migration records a technical source/public-access review, publisher terms URL, attribution
expectation, and a 30-day retention window. An operator should replace, expire, or revoke that
approval if an organisation-specific policy or legal review requires different treatment.

## Runtime and recovery

The scheduler discovers eligible subscriptions and enqueues one `INGEST_SOCIAL_SOURCE` job per
subscription. Provider failures update only that subscription's circuit/backoff state. Pages are
committed with their cursor and durable processing rows in one PostgreSQL transaction, so replay
is safe and a failed transaction cannot advance the cursor.

Processing runs separately through `PROCESS_SOCIAL_DOCUMENTS`; failures release a document with
capped exponential backoff. `AGGREGATE_SOCIAL_SIGNALS` writes immutable-window snapshots.
Synthetic traders ignore these snapshots unless `STOCKBALL_SOCIAL_SIGNALS_ENABLED=true`, and
ignore snapshots older than `STOCKBALL_SOCIAL_SIGNAL_MAX_AGE_SECONDS`.

Every processed document receives a general topic/sentiment classification in
`social_observations`. Sentiment is one of `POSITIVE`, `NEGATIVE`, `NEUTRAL`, or `MIXED`, with a
numeric score from -1 to 1. Injury/recovery documents additionally receive a linked row in
`social_injury_observations`; only that specialized row may change an injury episode. Ambiguous
and unresolved observations are retained for review but excluded from player signal snapshots.

The general resolver treats globally unique first/surnames and club-context-unique first/surnames
as full-confidence sentiment matches. Club shorthand is an explicit reviewed mapping in
`observations/resolution.py`; operators should update it as supported clubs change. These guesses
never flow into injury episode resolution, which continues to require a full name or reviewed
player alias.

To replay, clear or replace only the target subscription's opaque cursor after recording an
operator audit event. The `(provider, external_id)` uniqueness constraint prevents duplicate
documents and classifier-version uniqueness prevents duplicate observations.

## Revocation and retention

Set the source to disabled and its policy to `REVOKED` (or `EXPIRED`), then run
`SELECT enforce_social_retention(now())`. It clears retained text, tombstones matching documents,
and invalidates derived injury observations. Processing also rechecks current eligibility, so a
document queued before revocation cannot later change an episode.

## Adapter checklist

An adapter implements `SocialConnector.poll`, accepts an opaque cursor, returns normalized
documents, maps throttling to `RateLimited`, and maps temporary and configuration failures to the
shared error types. It must bound network and parsing work, use stable external identities, avoid
secrets in cursor/configuration JSON, and pass replay, malformed-response, timeout, and rate-limit
tests. Provider payloads belong only in document metadata and never in injury or trading modules.
