# Twitter Injury Intelligence

## Scope And Boundary

This worker-owned, opt-in pipeline reads public posts only through the approved X API
v2 recent-search endpoint. It contains no HTML client, browser automation, or scraper.
It writes injury evidence, episodes, and compact availability observations. It does not
write prices, cash, positions, orders, trades, or strategy decisions.

V1 uses a deterministic rules classifier. `InjuryClassifier` is a narrow interface for
a future replacement, but `RuleBasedInjuryClassifier` remains the default so ingestion
has no hidden LLM/model dependency, network call, prompt drift, or non-reproducible label.

## X Policy Gate

X's current restricted-use guidance states that developers must not infer or store
sensitive health information about X users, and its policy restricts off-X identity
matching. An injury pipeline may fall within those restrictions even when it processes
public professional-sports reporting.

For that reason:

- The schedule defaults to disabled.
- The client refuses to run unless `STOCKBALL_TWITTER_POLICY_ACKNOWLEDGED=true`.
- That acknowledgement must only be set after the exact developer use case, professional
  player identity mapping, derived injury fields, retention, and deletion process have
  been approved by the organization's policy/legal owner and, where required, X.
- The acknowledgement is a deployment guard, not proof of compliance.
- If the approved X access tier requires compliance-event processing, deletion
  reconciliation must be operational before production ingestion.

Review the current X Developer Agreement, Developer Policy, restricted-use guidance,
and compliance-stream availability before each deployment:

- `https://docs.x.com/developer-terms/agreement`
- `https://docs.x.com/developer-terms/policy`
- `https://docs.x.com/developer-terms/restricted-use-cases`
- `https://docs.x.com/x-api/compliance/streams/introduction`

## Retrieval And Cursors

`TwitterRecentSearchClient` calls only:

```http
GET https://api.x.com/2/tweets/search/recent
Authorization: Bearer $STOCKBALL_TWITTER_BEARER_TOKEN
```

The request uses the configured query, `sort_order=recency`, `max_results` from 10 to
100 and only post fields needed for attribution and audit. Source attribution uses the
post's immutable `author_id`; no user expansion/profile fields are requested. X recent
search currently covers the most recent seven days, so polling must be frequent enough
not to leave a gap.

Polling uses `since_id` and opaque `next_token` values:

1. The repository loads the stable cursor for a query key.
2. The first page is requested with the committed `since_id`.
3. Its `newest_id` is stored as `pending_newest_id`.
4. Each `next_token` page is checkpointed with the original `since_id`, opaque token,
   and first-page pending ID. The token is never modified.
5. Only after the final page succeeds is `pending_newest_id` promoted to `since_id`.
6. A crash resumes the saved page token. Replayed posts are idempotent by X post ID,
   and unprocessed observations can finish episode processing on the next poll.
7. `STOCKBALL_TWITTER_MAX_PAGES_PER_POLL` bounds each job. If more pages remain, the next
   job resumes instead of advancing the committed cursor.

The client imposes a minimum request interval. It records the X rate-limit limit,
remaining count, and reset timestamp in the cursor row. On HTTP 429 it uses
`Retry-After` or `x-rate-limit-reset`; it sleeps and retries once only when the wait is
within `STOCKBALL_TWITTER_MAX_RATE_LIMIT_SLEEP_SECONDS`. Longer waits and temporary 5xx
responses become retryable worker failures and use the existing Redis retry queue.
Authentication/access-tier failures are non-retryable.

## Stored X Data

Post text is held only in memory for classification and player resolution. It is not
stored. Follower counts, engagement metrics, profile descriptions, media, and URLs are
not requested or stored.

`twitter_injury_posts` stores the post ID, author ID, reviewed source-account foreign key,
post timestamp, language, conversation/reference/edit IDs, and ingestion timestamp.
These are still X Content and remain subject to the current
agreement, retention, edit, deletion, protected-account, suspension, and redistribution
requirements. `deleted_at` supports compliance removal state, but deployments must
provide the deletion-event/reconciliation operation required by their access tier.

Unregistered authors are skipped and not persisted. Post text never appears in evidence
details, logs, job payloads, or compact availability observations.

## Source Registry

Sources are never discovered or promoted automatically. Operators seed a JSON allowlist
and sync it with:

```bash
scripts/local-ingestion.sh twitter-sources \
  --registry services/worker/app/ingestion/social/twitter/registry.example.json
```

Every source requires X user ID, handle, display name, category, reviewer, review time,
review notes, and optional metadata such as club, publication affiliation, coverage
remit, and an internal review-ticket reference.

Weights are:

- `OFFICIAL_CLUB`: default `1.00`, highest trust.
- `OFFICIAL_LEAGUE`: default `1.00`, highest trust.
- `PLAYER_OWNED`: default `1.00`, highest trust.
- `CURATED_JOURNALIST`: starts at `0.95`.
- `FAN`: default `0.25` and cannot exceed `0.40`.

Official club/league and player-owned entries are fixed at `1.00`; curated journalists
cannot exceed `0.95`. Registry sync is authoritative: sources and aliases omitted from
the synced file are disabled before included entries are upserted.

Credible journalists are gathered only by adding candidates to the configured seed
allowlist, manually confirming identity, current affiliation, football/injury-reporting
remit, and recording reviewer metadata. No crawler assigns journalist status, no
automatic "reputation" score is claimed, and follower count is neither requested nor
used as factual credibility. Changes to affiliation or remit require another manual
review and registry sync.

Fan classifications are capped at low confidence and marked `aggregate_only`. They
cannot create, update, or recover an episode. `player_twitter_injury_fan_signal_daily` exposes
only daily per-player aggregate counts for possible future attention context.

## Player Resolution

Canonical `players.id` remains the identity. The resolver indexes:

- Exact canonical player display names.
- Manually reviewed `NAME`, `NICKNAME`, and `HANDLE` entries in `twitter_player_aliases`.
- Optional club hints on aliases and source-account metadata.

Matching is case/diacritic/punctuation normalized but requires an exact alias boundary;
there is no fuzzy guess. A unique alias match resolves the player. If the same alias
matches multiple players, an exact reviewed source-club hint may disambiguate it.
Otherwise the observation is stored as `AMBIGUOUS` with all candidate IDs and does not
touch an episode. No match is stored as `UNRESOLVED`. This prevents vague or same-name
posts from double-counting injury penalties.

## V1 Classification

The baseline classifier uses explicit regular expressions and is fully unit tested:

- Confirmed injury: `ruled out`, `will miss`, `diagnosed`, `suffered`, surgery,
  `out for`, or `sidelined`, together with an injury noun/type.
- Suspected injury: injury concern, knock, limped off, fitness doubt, assessment,
  scan, `could/may/might miss`, or doubtful.
- Suspected recovery evidence: return/back/resumed full or team training, returned
  or named in the squad, or available for selection.
- Strong recovery evidence: fit and available, medically cleared, fully fit, cleared
  to play, or explicit match participation such as played/completed N minutes.
- Negation: phrases such as `not injured`, `no injury`, `injury ruled out`, and
  `not returned/back/fit/available` suppress the corresponding evidence.
- Uncertainty: reportedly, unconfirmed, rumoured, possibly, appears, seems, could,
  may, and might reduce confidence by 30 percent.
- Extracted body areas include Achilles, ankle, back, calf, foot, groin, hamstring,
  head, hip, knee, shoulder, and thigh.
- Extracted types include concussion, fracture, illness, rupture, sprain, strain,
  and tear.
- Explicit day/week/month single values, ranges, and `a couple/few/several weeks`
  produce minimum/maximum absence days.

Rules cannot understand arbitrary paraphrases, sarcasm, images, video, context outside
the post, or complex negation scope. A future classifier may implement
`InjuryClassifier.classify(text, source)`, but it must return the same structured
contract, preserve confidence/source gates, be separately approved, and cannot silently
replace the deterministic default.

## Episode Lifecycle

Every episode's `stage` is exactly one of:

1. `SUSPECTED_INJURY`
2. `CONFIRMED_INJURY`
3. `SUSPECTED_RECOVERY`
4. `CONFIRMED_RECOVERED`

Transitions and matching:

- Actionable suspected evidence creates `SUSPECTED_INJURY`.
- Confirmed injury evidence with source-adjusted confidence at least `0.75` creates
  or moves the active episode to `CONFIRMED_INJURY`. Curated journalists can cross
  this threshold from their `0.95` starting trust.
- Later injury evidence attaches to the one active player episode. Extracted injury
  type/body area are filled when available, and later explicit absence windows extend,
  never shorten, the expected maximum absence.
- Return-to-training, squad, or lower-authority recovery evidence at confidence at
  least `0.65` moves the episode to `SUSPECTED_RECOVERY`.
- Only recovery language from an official club/league account at confidence at least
  `0.90`, or explicit match-participation evidence at confidence at least `0.90`,
  moves it to `CONFIRMED_RECOVERED`.
- Existing fixture-linked `player_stat_observations` may provide match participation
  only when the fixture is final (`FT`, `AET`, or `PEN`) and numeric minutes are greater
  than zero after the injury's last evidence. No new fixture/lineup/stats provider is
  introduced.
- A confirmed injury mention during suspected recovery is treated as a setback in the
  same episode and returns it to `CONFIRMED_INJURY`.
- Injury evidence after `CONFIRMED_RECOVERED` creates a new episode linked through
  `recurrence_of_episode_id`.
- Negated, unclassified, aggregate-only fan, unresolved, and ambiguous observations
  never create or transition episodes.

Expected sidelined periods and expiration:

- `expected_absence_until` is the post time plus the extracted maximum absence.
- An explicit window remains active through that maximum plus 14 days of grace.
- A suspected episode without a window expires after 14 days if not confirmed.
- A confirmed episode without a window expires after 180 days if no later evidence
  arrives.
- Suspected recovery expires after 30 days without strong recovery or setback evidence.
- Expiration sets `expired_at`; it does not invent a fifth stage. Expired episodes drop
  out of `player_current_injury_availability`.

## Future Bot Read

`player_injury_availability_observations` is append-only compact context containing
player, episode, one of the four stages, confidence, expected return, type/body area,
evidence kind, source category, observation time, and `is_available` (true only for
confirmed recovered). `player_current_injury_availability` returns the latest unexpired
observation per player.

Bots may eventually read this view as one input among stats, market, and social context.
This task deliberately does not connect it to any strategy engine. The pipeline never
mutates instrument prices, cash, positions, trades, or orders and never calls the
trading engine.

## Configuration And Commands

```bash
STOCKBALL_TWITTER_BEARER_TOKEN=replace-with-secret
STOCKBALL_TWITTER_SEARCH_QUERY='(injury OR injured OR "ruled out" OR "returned to training") lang:en -is:retweet'
STOCKBALL_TWITTER_QUERY_KEY=premier-league-injuries-v1
STOCKBALL_TWITTER_POLICY_ACKNOWLEDGED=false
STOCKBALL_TWITTER_REQUEST_INTERVAL_SECONDS=1
STOCKBALL_TWITTER_MAX_RATE_LIMIT_SLEEP_SECONDS=60
STOCKBALL_TWITTER_MAX_RESULTS=100
STOCKBALL_TWITTER_MAX_PAGES_PER_POLL=10
STOCKBALL_TWITTER_INJURY_SCHEDULE_ENABLED=false
STOCKBALL_TWITTER_INJURY_SCHEDULE_INTERVAL_MINUTES=5
STOCKBALL_TWITTER_BROWSER_ENABLED=false
STOCKBALL_TWITTER_BROWSER_USER_DATA_DIR=
STOCKBALL_TWITTER_BROWSER_PROFILE_DIRECTORY=
```

Apply migration and sync reviewed identities:

```bash
scripts/local-ingestion.sh migrate
scripts/local-ingestion.sh twitter-sources --registry /path/to/reviewed-registry.json
```

Run one poll:

```bash
STOCKBALL_TWITTER_POLICY_ACKNOWLEDGED=true scripts/local-ingestion.sh twitter-injuries
```

Enable scheduling only after policy approval, registry review, query validation,
credentials, access tier, rate budget, retention, and compliance deletion operations
are confirmed:

```bash
STOCKBALL_TWITTER_POLICY_ACKNOWLEDGED=true
STOCKBALL_TWITTER_INJURY_SCHEDULE_ENABLED=true
```

The scheduler creates one `INGEST_TWITTER_INJURIES` job per configured interval window.
Redis claim keys prevent duplicate scheduling; PostgreSQL post IDs, evidence uniqueness,
and cursor checkpoints make job retries idempotent.
