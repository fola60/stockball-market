# Worker Ingestion Module

## Purpose

Owns all external data intake.

Ingestion answers: "What did the outside world say?"

## Responsibilities

- Fetch or scrape external data.
- Normalize provider-specific data into internal records.
- Store raw or normalized provider observations.
- Handle provider IDs, rate limits, retries, and failures.
- Keep provider-specific code away from trading and bot strategy modules.

## Submodules

- `players`: Premier League player identity and squad data.
- `market_values`: external player market-value data.
- `fixtures`: fixture, lineup, and match-status data.
- Future `stats`: player performance data from external providers.
- Future `social`: social mention and post data from external providers.
- Future `news`: football news and transfer-rumor data.
- Future `providers`: shared provider clients, auth, rate limiting, and response normalization.

## V1 Player Universe And Valuation Approach

Use a provider-backed ingestion flow rather than one-off seed SQL for the Premier League player universe. The same job must be safe to rerun because player club and league membership changes over time.

Recommended source split:

- Player identity, squads, clubs, positions, nationality, and date of birth: use API-Football as the V1 canonical provider. API-Football also supplies fixtures and per-fixture player stats, so using it for players avoids cross-provider ID matching for V1 stats ingestion.
- Market value: do not assume the squad provider will supply usable player market values. Most football fixture/stat APIs do not provide Transfermarkt-style market valuations. Use a separate market-value provider or licensed dataset if we need real transfer-market-style valuations.
- Development fallback: allow a manually curated CSV for market values so local seeding can proceed without scraping or committing to a paid provider. The CSV should include source, source player ID or source URL, value, currency, observed date, and enough identity fields to reconcile to a canonical player.

Avoid building against direct Transfermarkt scraping as the default path. Transfermarkt is the obvious market-value reference, but scraping creates operational and licensing risk. If Transfermarkt-derived values are used, prefer a licensed provider, explicit permission, or an internal/manual import path that records the source and observation date.

## Provider Identity Strategy

Do not use one external provider ID as the Stockball player ID. Stockball should maintain a canonical `players.id`, then attach provider references to that player.

The current schema stores `provider` and `provider_player_id` on `players`. Before multi-source ingestion, replace or augment that with a mapping table such as:

```sql
player_provider_refs (
    player_id uuid not null references players(id),
    provider text not null,
    provider_player_id text not null,
    provider_url text,
    confidence numeric(4, 3),
    is_primary boolean not null default false,
    first_seen_at timestamptz not null,
    last_seen_at timestamptz not null,
    raw_identity jsonb not null default '{}'::jsonb,
    unique (provider, provider_player_id)
)
```

Reconciliation order:

1. Match by an existing `(provider, provider_player_id)` reference.
2. Match by a verified cross-provider mapping if a provider supplies one.
3. Match deterministically by normalized name, date of birth, nationality, and current club.
4. Queue ambiguous matches for admin review instead of guessing.

Store raw provider payloads or normalized observations for auditability. Canonical player fields should represent Stockball's current best view; provider observations should remain available when later imports disagree.

## Rerunnable Jobs

Player and valuation ingestion should be idempotent.

- A Premier League squad sync should upsert canonical players, update current club/position metadata, mark provider refs as seen, and record whether the player is currently in the Premier League universe.
- A player leaving the Premier League should not be deleted. Mark them inactive/out-of-universe and let the instrument policy decide whether to keep trading, freeze, or delist.
- A market-value sync should append a new observed value when the provider value or observation timestamp changes. It should not overwrite history.
- Instrument creation should be a separate seeding step that reads canonical players plus the latest accepted market value.

## Boundaries

- Does not execute trades.
- Does not directly change instrument prices.
- Does not decide bot trades.
- Writes facts and observations that other modules can interpret.
